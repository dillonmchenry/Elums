/**
 * =============================================================================
 * NanoPitch -- Lightweight Real-Time Vocal Pitch Analysis Engine
 * =============================================================================
 *
 * WHAT THIS FILE IS
 * -----------------
 * This is the C header for the NanoPitch inference engine.  It declares every
 * data structure and function needed to run a trained deep-learning model that
 * converts raw audio into a pitch estimate (fundamental frequency, f0) in real
 * time.  The implementation lives in the corresponding .c file; this header is
 * the "contract" that any caller -- including JavaScript in a web browser --
 * programs against.
 *
 *
 * WHY C AND WASM?
 * ---------------
 * WebAssembly (WASM) is a compact binary instruction format that runs inside
 * every modern web browser at near-native speed.  By writing the inference
 * engine in plain C (no C++ STL, no dynamic dispatch) we can compile it with
 * Emscripten or Clang to a .wasm module that a web page loads and calls
 * directly from JavaScript.  This means:
 *
 *   1. No server round-trip -- inference happens on the user's device.
 *   2. Low latency         -- WASM runs in a dedicated thread or AudioWorklet.
 *   3. Privacy              -- audio never leaves the browser.
 *   4. Portability          -- the same .wasm binary works on every OS/browser.
 *
 * The alternative would be shipping a Python/PyTorch model behind a server,
 * which adds network latency and requires GPU hosting.  For a real-time pitch
 * tracker that must respond within a single audio frame (10 ms), client-side
 * WASM is the practical choice.
 *
 *
 * THE SIGNAL-PROCESSING PIPELINE (high level)
 * --------------------------------------------
 *   raw audio (160 samples @ 16 kHz, i.e. 10 ms)
 *       |
 *       v
 *   [Mel Spectrogram]  -- time-frequency representation (40 bands)
 *       |
 *       v
 *   [Conv1 -> Conv2]   -- two 1-D causal convolutions, learn local patterns
 *       |
 *       v
 *   [GRU x 3 layers]   -- recurrent network captures temporal context
 *       |
 *       v
 *   [Dense heads]       -- two output layers:
 *       |                    pitch posteriorgram  (360 classes)
 *       |                    voice-activity score (1 scalar)
 *       v
 *   [Viterbi decoder]   -- smooths the raw pitch posteriors over time
 *       |
 *       v
 *   f0 in Hz (or "unvoiced")
 *
 *
 * MEL SPECTROGRAM -- what it is and why we use it
 * ------------------------------------------------
 * A mel spectrogram is a time-frequency representation of audio that mimics
 * how the human ear perceives pitch.  The processing steps are:
 *
 *   1. Windowing:  Multiply each short chunk of audio by a Hann window so that
 *      the chunk's edges taper to zero (reduces spectral leakage).
 *   2. FFT:  Apply a 512-point Fast Fourier Transform to get the magnitude
 *      spectrum -- a list of energy values at each frequency bin.
 *   3. Mel filterbank:  Multiply the magnitude spectrum by a bank of 40
 *      overlapping triangular filters whose center frequencies are equally
 *      spaced on the *mel scale*.  The mel scale is roughly logarithmic above
 *      ~1 kHz, matching the fact that humans perceive the octave from 1 kHz to
 *      2 kHz as the "same size" as the octave from 2 kHz to 4 kHz, even
 *      though the latter spans twice as many Hz.  This compression lets 40
 *      mel bands capture perceptually relevant detail that would take hundreds
 *      of linear frequency bins.
 *   4. Log compression:  Take the natural log of each mel-band energy (plus a
 *      tiny offset to avoid log(0)).  The log maps the enormous dynamic range
 *      of audio power into a compact range that neural networks train on more
 *      easily.
 *
 * The specific parameters below were chosen to match the Python training code
 * exactly, so the C inference reproduces the same features the model was
 * trained on:
 *
 *   Sample rate : 16 000 Hz   -- telephone/voice bandwidth, sufficient for f0
 *   FFT size    : 512         -- gives 257 frequency bins (512/2 + 1)
 *   Hop length  : 160 samples -- 10 ms between successive frames
 *   Window len  : 400 samples -- 25 ms analysis window (overlaps by 15 ms)
 *   Mel bands   : 40          -- compact but sufficient for vocal pitch
 *   Freq range  : 0-8000 Hz   -- Nyquist is 8 kHz; we use the full range
 *   Mel variant : HTK         -- the classic Hidden Markov Model Toolkit scale
 */

#ifndef NANOPITCH_H
#define NANOPITCH_H

#include <stdint.h>

/* =========================================================================
 * Section 1 -- Mel Spectrogram Constants
 * =========================================================================
 * These #defines pin the spectrogram parameters at compile time.  Because
 * every constant is a literal, the compiler can size all arrays statically
 * and avoid any heap allocation for the mel path.
 */

/** Audio sample rate in Hz.  16 kHz is standard for speech/voice models. */
#define NC_SAMPLE_RATE   16000

/** FFT size.  512 points at 16 kHz gives ~31 Hz per bin -- fine enough to
 *  resolve the harmonics of a typical singing voice (80-1000 Hz f0). */
#define NC_N_FFT         512

/** Number of *non-negative* frequency bins in the FFT output.
 *  A real-valued FFT of size N produces N/2+1 unique bins (the upper half
 *  is the complex conjugate mirror of the lower half). */
#define NC_N_FREQS       257     /* N_FFT/2 + 1 */

/** Hop length -- the stride between successive analysis frames, in samples.
 *  160 samples at 16 kHz = 10 ms.  This is the fundamental time resolution
 *  of the model: we produce one pitch estimate every 10 ms. */
#define NC_HOP_LENGTH    160

/** Analysis window length in samples.  400 samples at 16 kHz = 25 ms.
 *  The window is longer than the hop, so consecutive frames overlap by
 *  400 - 160 = 240 samples (15 ms).  Overlap is essential: without it, a
 *  pitch cycle that straddles the boundary between two frames would be
 *  partially cut off, degrading the spectral estimate. */
#define NC_WIN_LENGTH    400

/** Number of mel-frequency bands.  40 is a common choice for voice models
 *  (ASR systems often use 40 or 80).  Each band integrates energy from a
 *  triangular filter whose width increases with frequency, paralleling
 *  the decreasing frequency resolution of the human cochlea. */
#define NC_N_MELS        40

/** Tiny constant added before taking log, preventing log(0) = -inf.
 *  The value 1e-10 is small enough to be inaudible but large enough to
 *  keep floating-point math well-behaved. */
#define NC_LOG_OFFSET    1e-10f

/* =========================================================================
 * Section 2 -- Model Architecture Constants
 * =========================================================================
 *
 * PITCH BINS AND THE POSTERIORGRAM
 * --------------------------------
 * The model treats pitch estimation as a *classification* problem rather
 * than a regression problem.  Instead of predicting a single continuous Hz
 * value, it outputs a probability distribution over 360 discrete pitch
 * "bins."  This distribution is called a **pitch posteriorgram** (posterior
 * probability + spectrogram-like grid).
 *
 * The 360 bins cover 6 octaves at 20-cent resolution:
 *
 *   - One octave = 1200 cents (a logarithmic unit of pitch).
 *   - 6 octaves / 20 cents per bin = 6 * 60 = 360 bins.
 *   - Typical range: ~B0 (31.7 Hz) to ~B6 (~2006 Hz), which spans the
 *     full range of human singing and most musical instruments.
 *   - 20 cents is roughly 1/5 of a semitone -- fine enough to detect
 *     vibrato and pitch bends, yet coarse enough that 360 sigmoid outputs
 *     remain tractable.
 *
 * Classification has important advantages over regression for pitch:
 *   - The loss function (cross-entropy) naturally handles the multimodal
 *     ambiguity that occurs when harmonics compete for the "true" f0.
 *   - The full posterior lets downstream code reason about confidence:
 *     a sharp peak means high certainty; a flat distribution means noise.
 *   - Viterbi decoding (see below) can use the posterior directly as an
 *     observation likelihood.
 *
 *
 * GRU NETWORKS -- what they are and why they suit audio
 * -----------------------------------------------------
 * A GRU (Gated Recurrent Unit) is a type of recurrent neural network cell
 * designed to model sequential data.  At each time step t the GRU takes:
 *   - an input vector  x_t   (here: the conv output for the current frame)
 *   - the previous hidden state  h_{t-1}
 * and produces a new hidden state  h_t  via two learned "gates":
 *
 *   reset gate  r_t = sigma(W_r * [x_t, h_{t-1}])
 *   update gate z_t = sigma(W_z * [x_t, h_{t-1}])
 *   candidate   n_t = tanh(W_n * [x_t, r_t . h_{t-1}])
 *   output      h_t = (1 - z_t) . n_t  +  z_t . h_{t-1}
 *
 * The *update gate* z_t controls how much of the old state to keep vs.
 * replace -- this is what lets GRUs "remember" information across many
 * frames without suffering from vanishing gradients.  The *reset gate* r_t
 * lets the cell "forget" irrelevant history when the signal changes
 * abruptly (e.g., a new note onset).
 *
 * Compared to LSTM cells, GRUs have fewer parameters (2 gates vs. 3) and
 * are therefore faster -- an important consideration when every frame must
 * be processed within 10 ms.  Three stacked GRU layers give the model
 * enough depth to capture hierarchical temporal patterns (short vibrato
 * cycles inside longer note sustains) while staying small enough for WASM.
 *
 * The weight matrices for each GRU follow PyTorch's convention:
 *   W_ih : input-to-hidden  [3*hidden_size, input_size]
 *   W_hh : hidden-to-hidden [3*hidden_size, hidden_size]
 *   b_ih : input-to-hidden bias  [3*hidden_size]
 *   b_hh : hidden-to-hidden bias [3*hidden_size]
 * The factor "3*" is because PyTorch packs the reset, update, and new-gate
 * weight rows into a single matrix for efficiency.
 */

/** Number of pitch classes in the output posteriorgram.
 *  360 bins = 6 octaves * (1200 cents/octave / 20 cents/bin). */
#define NC_PITCH_BINS    360

/** Output dimension of the first convolutional layer (and input to conv2).
 *  Think of this as the "conditioning" feature size -- it compresses the
 *  40 mel bands into a learned representation.  Marked "default" because
 *  the actual value is read from the weight file at load time. */
#define NC_COND_SIZE     64     /* default, overridden by weights */

/** Hidden dimension of each GRU layer.  Larger = more capacity but slower.
 *  96 is a deliberate choice balancing accuracy and WASM throughput. */
#define NC_GRU_SIZE      96     /* default, overridden by weights */

/** Maximum supported layer size for stack-allocated buffers.
 *  cond_size and gru_size must both be <= this value.
 *  Increase if you need larger models (costs more stack memory). */
#ifndef NC_MAX_LAYER_SIZE
#define NC_MAX_LAYER_SIZE 512
#endif

/** Number of "warm-up" frames consumed by the causal convolution stack
 *  before valid output is available.
 *
 *  Each 1-D convolution with kernel size k=3 needs 2 past frames of
 *  context.  Two such layers back-to-back need 2+2 = 4 frames total.
 *  During these first 4 frames the convolution ring buffer is still
 *  filling, so we suppress the output and return zeros. */
#define NC_CONV_CONTEXT  4      /* 2 conv layers with k=3 each eat 4 frames */

/* =========================================================================
 * Section 3 -- Data Structures
 * =========================================================================
 *
 * Three structs partition the data a caller must manage:
 *
 *   NanoPitchWeights -- the learned model parameters (read-only after load)
 *   NanoPitchState   -- mutable inference state (hidden states, buffers)
 *   NanoPitchOutput  -- the result of processing one audio frame
 *
 * Separating weights from state means a single weight object can serve
 * multiple independent audio streams (e.g., two singers tracked in
 * parallel) simply by pairing it with separate state objects.
 */

/**
 * NanoPitchWeights -- all learned parameters of the neural network.
 *
 * These are loaded once from a flat binary/JSON weight file exported by
 * the Python training script and then treated as read-only during
 * inference.  The struct contains raw float pointers into heap-allocated
 * arrays; nanopitch_load_weights() populates them, and
 * nanopitch_free_weights() releases them.
 */
typedef struct {
    /** Actual conditioning size and GRU hidden size read from the weight
     *  file.  These may differ from the compile-time NC_COND_SIZE /
     *  NC_GRU_SIZE defaults if you retrain the model with different
     *  hyperparameters. */
    int cond_size;
    int gru_size;

    /* ----- Convolutional front-end -----
     *
     * Two 1-D convolutions act as a learned feature extractor that
     * replaces hand-crafted features (e.g., MFCC deltas).  Each has
     * kernel size k=3, meaning it looks at 3 consecutive mel frames to
     * produce one output frame.  "Causal" padding ensures the convolution
     * only uses current and past frames -- never future frames -- which
     * is essential for real-time streaming.
     *
     * Conv1 maps   n_mels (40)      -> cond_size (64)
     * Conv2 maps   cond_size (64)   -> gru_size  (96)
     */

    /* Conv1: transforms mel features into a learned "conditioning" space.
     * Weight shape [cond_size][n_mels][3]:
     *   - cond_size output channels
     *   - n_mels input channels
     *   - 3 time-steps (kernel width) */
    float *conv1_weight;    /* [cond_size][n_mels][3] */
    float *conv1_bias;      /* [cond_size] */

    /* Conv2: further compresses into the GRU's expected input dimension.
     * Weight shape [gru_size][cond_size][3]. */
    float *conv2_weight;    /* [gru_size][cond_size][3] */
    float *conv2_bias;      /* [gru_size] */

    /* ----- Stacked GRU layers -----
     *
     * Three GRU layers form the temporal backbone.  Each layer's hidden
     * state is a vector of length gru_size.  Stacking lets the model
     * learn increasingly abstract temporal features:
     *
     *   GRU1 -- captures frame-level acoustic detail (formant motion,
     *           harmonic shimmer).
     *   GRU2 -- captures note-level patterns (vibrato rate, portamento).
     *   GRU3 -- captures phrase-level context (key center, melodic arc).
     *
     * Each layer has four parameter tensors following PyTorch convention:
     *   w_ih  [3*gru_size, gru_size] -- input-to-hidden weights
     *   w_hh  [3*gru_size, gru_size] -- hidden-to-hidden (recurrent) weights
     *   b_ih  [3*gru_size]           -- input-to-hidden biases
     *   b_hh  [3*gru_size]           -- hidden-to-hidden biases
     *
     * The "3*" factor comes from packing the reset-gate, update-gate, and
     * new-gate matrices into one contiguous block (PyTorch convention).
     */
    float *gru1_w_ih;       /* [3*gru_size][gru_size] */
    float *gru1_w_hh;       /* [3*gru_size][gru_size] */
    float *gru1_b_ih;       /* [3*gru_size] */
    float *gru1_b_hh;       /* [3*gru_size] */

    float *gru2_w_ih;
    float *gru2_w_hh;
    float *gru2_b_ih;
    float *gru2_b_hh;

    float *gru3_w_ih;
    float *gru3_w_hh;
    float *gru3_b_ih;
    float *gru3_b_hh;

    /* ----- Dense output heads -----
     *
     * After the three GRU layers, their hidden states are concatenated
     * with the conv2 output to form a "super-vector" of size 4*gru_size
     * (conv2 output + gru1_h + gru2_h + gru3_h).  This concatenation is
     * a skip-connection trick: the dense heads can see both low-level
     * (conv) and high-level (GRU) features, improving gradient flow
     * during training and giving the output layers richer information.
     *
     * Two independent linear (fully connected) layers project this
     * super-vector into the two task-specific outputs:
     */

    /* VAD (Voice Activity Detection) head: predicts a single scalar
     * probability that the current frame contains voiced speech/singing.
     *
     * WHAT IS VAD AND WHY DOES IT MATTER?
     * Voice Activity Detection answers the binary question "is someone
     * singing/speaking right now?"  It matters because:
     *   - During silence or noise, the pitch head may still output a
     *     confident-looking posterior (neural nets always predict
     *     *something*).  VAD provides an independent gate: if VAD < 0.5,
     *     we set f0 = 0 ("unvoiced") regardless of the pitch posterior.
     *   - It lets the UI show "no pitch" instead of jittery false
     *     detections during breaths, rests, or ambient noise.
     *   - In training, the VAD head also provides a helpful auxiliary
     *     gradient signal that stabilises learning in unvoiced regions.
     *
     * The output is passed through a sigmoid so it lies in [0, 1]. */
    float *dense_vad_weight;  /* [1][4*gru_size] */
    float *dense_vad_bias;    /* [1] */

    /* Pitch head: predicts the 360-class pitch posteriorgram.
     * The output is passed through a sigmoid per bin (independent [0,1]
     * pseudo-probabilities; not softmax — they need not sum to 1).
     * Each bin corresponds to a 20-cent interval; the bin with the
     * highest probability indicates the model's best pitch guess, and
     * the distribution's shape conveys confidence. */
    float *dense_pitch_weight; /* [360][4*gru_size] */
    float *dense_pitch_bias;   /* [360] */
} NanoPitchWeights;

/**
 * NanoPitchState -- mutable per-stream inference state.
 *
 * HOW STREAMING / ONLINE INFERENCE WORKS
 * ---------------------------------------
 * Unlike offline (batch) inference where the entire audio file is available
 * at once, streaming inference processes audio *frame by frame* as it
 * arrives from the microphone.  This imposes two constraints:
 *
 *   1. Causality -- we can only use the current frame and past frames;
 *      future frames have not arrived yet.  The convolutions use "causal"
 *      padding, and the GRU naturally only looks backward.
 *   2. Persistence -- between frames we must remember:
 *      (a) the last few mel frames (for the causal convolution context),
 *      (b) each GRU layer's hidden state vector (the "memory"),
 *      (c) the overlap samples from the previous audio chunk (for the
 *          windowed FFT),
 *      (d) the Viterbi trellis column (for temporal pitch smoothing).
 *
 * This struct bundles all of that mutable state.  One NanoPitchState
 * object corresponds to one audio stream.  To track two singers, create
 * two states and call nanopitch_process_frame() on each independently
 * (they can share the same NanoPitchWeights).
 *
 * The call pattern from JavaScript (or any caller) is:
 *
 *   weights = nanopitch_load_weights(data, n, cond, gru);
 *   state   = nanopitch_create_state(gru);
 *
 *   // In the AudioWorklet's process() callback, every 10 ms:
 *   if (nanopitch_process_frame(weights, state, samples, &out)) {
 *       // out.f0_hz is the pitch; out.vad is voice confidence
 *   }
 *
 *   // When the user stops recording:
 *   nanopitch_reset_state(state, gru);   // or free it
 */
typedef struct {
    /* ---- Convolution ring buffer ----
     *
     * The two conv layers with kernel size 3 need access to the current
     * mel frame *plus* the 4 most recent past frames (see NC_CONV_CONTEXT).
     * We store these in a circular (ring) buffer of 5 slots.  A ring
     * buffer avoids copying data on every frame -- we just overwrite the
     * oldest slot and advance the position index. */
    float conv_buf[5][NC_N_MELS];
    int conv_buf_pos;

    /* ---- GRU hidden states ----
     *
     * Each GRU layer maintains a hidden-state vector of length gru_size.
     * These vectors are the "memory" of the recurrent network: they carry
     * information from all previously processed frames.  They are
     * heap-allocated because gru_size is only known at runtime (read from
     * the weight file). */
    float *gru1_h;   /* [gru_size] */
    float *gru2_h;   /* [gru_size] */
    float *gru3_h;   /* [gru_size] */

    /* ---- Mel spectrogram overlap buffer ----
     *
     * The analysis window (400 samples) is longer than the hop (160
     * samples), so each new frame reuses 240 samples from the previous
     * frame.  This buffer stores the last NC_WIN_LENGTH samples so we can
     * assemble the full 400-sample window from 240 old + 160 new. */
    float analysis_mem[NC_WIN_LENGTH];  /* overlap buffer */

    /** How many frames have been fed so far.  Used to detect the warm-up
     *  phase (frame_count < NC_CONV_CONTEXT) during which no valid output
     *  is produced. */
    int frame_count;

    /* ---- Online Viterbi state ----
     *
     * WHAT IS VITERBI DECODING AND WHY DO WE NEED IT?
     *
     * The raw pitch posterior from the neural network can be noisy: it
     * might jump between octaves on consecutive frames due to harmonic
     * ambiguity (a note at 220 Hz has strong energy at 440 Hz too, so the
     * model might flip between the two).
     *
     * The Viterbi algorithm is a dynamic-programming method originally
     * designed for Hidden Markov Models (HMMs).  We define:
     *   - States:  the 360 pitch bins + 1 "unvoiced" state  (361 total)
     *   - Observations:  the pitch posterior + VAD score each frame
     *   - Transition probabilities:  a matrix that penalises large
     *     pitch jumps between consecutive frames (e.g., jumping 5
     *     semitones in 10 ms is very unlikely for a human voice)
     *
     * At each frame the algorithm maintains, for every state, the log-
     * probability of the *best path* ending in that state.  It then
     * combines this with the new observation likelihoods and the
     * transition penalties to find the new best-path scores.  The state
     * with the highest score gives the smoothed pitch.
     *
     * In the standard (offline) Viterbi you would also store backpointers
     * and retrace the entire best path at the end.  For real-time use we
     * run "online Viterbi": we only keep the *current* column of scores
     * (no backpointers, no look-ahead), so the estimate is slightly less
     * accurate than a full offline decode but has zero additional latency.
     *
     * viterbi_prev stores the log-probability column: one entry per pitch
     * bin plus one entry for the "unvoiced" state.  last_f0 caches the
     * most recently decoded frequency in Hz (0 = unvoiced). */
    float *viterbi_prev;  /* [PITCH_BINS + 1] log probabilities */
    float last_f0;
} NanoPitchState;

/**
 * NanoPitchOutput -- the result produced for a single 10 ms audio frame.
 *
 * This struct is filled in by nanopitch_process_frame() and contains
 * everything a caller (UI, tuner display, MIDI converter) might need.
 */
typedef struct {
    /** Voice Activity Detection score in [0, 1].
     *  Values close to 1 mean "someone is singing"; close to 0 means
     *  silence/noise.  A common threshold is 0.5. */
    float vad;                   /* voice activity [0, 1] */

    /** The raw pitch posteriorgram -- a 360-element probability vector
     *  whose entries sum to 1.  Each element corresponds to a 20-cent
     *  pitch bin spanning 6 octaves.  You can visualise this as a single
     *  column of a "piano-roll probability image."  Useful for:
     *    - Drawing a pitch-confidence heat map in the UI
     *    - Feeding into a custom post-processing / smoothing algorithm
     *    - Analysing harmonic ambiguity (multiple peaks = octave error
     *      risk) */
    float pitch_posterior[NC_PITCH_BINS]; /* pitch posteriorgram */

    /** The final pitch estimate in Hz, produced by Viterbi decoding of
     *  the posterior.  A value of 0.0 means "unvoiced" (silence, noise,
     *  or breath).  This is the number you would send to a guitar tuner
     *  display or a MIDI note converter. */
    float f0_hz;                 /* Viterbi-decoded f0 (Hz), 0 = unvoiced */

    /** The 40-band log-mel spectrogram frame that was fed to the neural
     *  network.  Exposed here so a UI can draw a live spectrogram
     *  visualisation alongside the pitch trace without recomputing it. */
    float mel[NC_N_MELS];       /* input log-mel (for visualization) */
} NanoPitchOutput;

/* =========================================================================
 * Section 4 -- Public API
 * =========================================================================
 *
 * The API follows a simple lifecycle:
 *
 *   LOAD       nanopitch_load_weights()   -- parse weight file, allocate
 *   CREATE     nanopitch_create_state()   -- allocate per-stream state
 *   PROCESS    nanopitch_process_frame()  -- call once per 10 ms frame
 *   (optional) nanopitch_reset_state()    -- reuse state for a new stream
 *   FREE       nanopitch_free_state()     -- release state memory
 *              nanopitch_free_weights()   -- release weight memory
 *
 * All functions use C linkage (extern "C") so they can be called from
 * JavaScript through Emscripten's ccall/cwrap without C++ name mangling.
 */

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Load model weights from a flat float array.
 *
 * The caller obtains this array by fetching the exported weight file
 * (JSON or binary) and decoding it into a contiguous float buffer.
 * The function slices the flat array into the individual weight tensors
 * listed in NanoPitchWeights, allocating heap memory for each.
 *
 * @param data       Pointer to the flat float array of all weights.
 * @param n_floats   Total number of floats in `data` (used for bounds
 *                   checking).
 * @param cond_size  The conditioning dimension the model was trained with
 *                   (must match the weight file).
 * @param gru_size   The GRU hidden dimension the model was trained with
 *                   (must match the weight file).
 * @return           A heap-allocated NanoPitchWeights pointer, or NULL if
 *                   the array is too small or allocation fails.
 */
NanoPitchWeights* nanopitch_load_weights(const float *data, int n_floats,
                                          int cond_size, int gru_size);

/**
 * Free all memory owned by a NanoPitchWeights object.
 * Safe to call with NULL (no-op).
 */
void nanopitch_free_weights(NanoPitchWeights *w);

/**
 * Allocate and zero-initialize a new inference state.
 *
 * All hidden states start at zero, meaning the GRU has no prior context.
 * The first NC_CONV_CONTEXT frames (40 ms) will produce no output while
 * the convolution ring buffer fills.
 *
 * @param gru_size  Must match the gru_size used in load_weights.
 * @return          A heap-allocated NanoPitchState, or NULL on failure.
 */
NanoPitchState* nanopitch_create_state(int gru_size);

/**
 * Free all memory owned by a NanoPitchState object.
 * Safe to call with NULL.
 */
void nanopitch_free_state(NanoPitchState *st);

/**
 * Reset an existing state to its initial (all-zeros) condition.
 *
 * Call this when starting a new audio stream without wanting to free and
 * re-allocate.  For example, if the user presses "stop" and then "record"
 * again, resetting avoids carrying stale GRU memory and Viterbi state
 * from the previous recording into the new one.
 *
 * @param st        The state to reset.
 * @param gru_size  Must match the gru_size the state was created with.
 */
void nanopitch_reset_state(NanoPitchState *st, int gru_size);

/**
 * Process one audio frame -- the main entry point for streaming inference.
 *
 * Call this function once every 10 ms with exactly NC_HOP_LENGTH (160)
 * new audio samples at 16 kHz.  Internally it:
 *
 *   1. Computes the log-mel spectrogram for the frame.
 *   2. Pushes the mel vector into the convolution ring buffer.
 *   3. If enough frames have accumulated (frame_count >= NC_CONV_CONTEXT),
 *      runs the two convolutions, three GRU steps, and two dense heads.
 *   4. Runs the online Viterbi decoder to smooth the pitch posterior.
 *   5. Writes the results into `out`.
 *
 * During the warm-up period (the first NC_CONV_CONTEXT = 4 frames, i.e.
 * 40 ms), the function returns 0 and `out` is zeroed.  After warm-up it
 * returns 1 and `out` contains valid results.
 *
 * @param w            Model weights (read-only).
 * @param st           Per-stream mutable state (updated in place).
 * @param audio_frame  Pointer to NC_HOP_LENGTH (160) float samples,
 *                     expected range roughly [-1, 1].
 * @param out          Output struct to fill.
 * @return             1 if `out` is valid, 0 during warm-up.
 */
int nanopitch_process_frame(const NanoPitchWeights *w,
                            NanoPitchState *st,
                            const float *audio_frame,
                            NanoPitchOutput *out);

/**
 * Compute the log-mel spectrogram for a single frame (low-level utility).
 *
 * This is exposed separately so callers who want only the mel features
 * (e.g., for visualisation or for feeding into a different model) can
 * call it without running the neural network.
 *
 * Internally this function:
 *   1. Assembles a 400-sample window from the 240 samples retained in
 *      st->analysis_mem and the 160 new samples in audio_frame.
 *   2. Applies a Hann window.
 *   3. Computes a 512-point real FFT -> 257 magnitude bins.
 *   4. Multiplies by the 40-band mel filterbank.
 *   5. Takes log(energy + NC_LOG_OFFSET) for each band.
 *   6. Updates st->analysis_mem with the new samples for next time.
 *
 * @param st           State (analysis_mem is read and updated).
 * @param audio_frame  NC_HOP_LENGTH (160) new samples.
 * @param out_mel      Output buffer of NC_N_MELS (40) floats.
 */
void nanopitch_compute_mel(NanoPitchState *st,
                           const float *audio_frame,
                           float *out_mel);

#ifdef __cplusplus
}
#endif

#endif /* NANOPITCH_H */
