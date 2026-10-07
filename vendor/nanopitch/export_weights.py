#!/usr/bin/env python3
"""
Export NanoPitch PyTorch weights to JSON format for WASM deployment.

WHY DO WE NEED THIS SCRIPT?

Neural networks for audio (pitch detection, voice activity detection, etc.)
are typically trained in Python using PyTorch or TensorFlow. But for real-time
audio applications in the browser — like a web-based guitar tuner, a vocal
pitch monitor, or a DAW plugin — we need the model to run as WebAssembly (WASM)
compiled from C code. The browser cannot directly load a PyTorch .pth file.

This script bridges the gap: it reads a trained PyTorch model checkpoint and
writes out all the learned weight values as a simple JSON file. The JSON is
then loaded by JavaScript in the browser, which passes the raw float array
to the C/WASM inference engine via nanopitch_load_weights().

    Training (Python/PyTorch)
         |
         v
    export_weights.py  <--- THIS SCRIPT
         |
         v
    model.json  (flat array of floats + metadata)
         |
         v
    Browser loads JSON  -->  JavaScript copies floats into WASM heap
         |
         v
    nanopitch_load_weights() in C  -->  real-time pitch detection

HOW PYTORCH STORES MODEL WEIGHTS (state_dict)

When you train a neural network in PyTorch, the learned parameters (weights
and biases) live inside nn.Module objects. PyTorch provides model.state_dict(),
which returns an OrderedDict mapping string names to tensors:

    {
        'conv1.weight': tensor of shape [64, 40, 3],
        'conv1.bias':   tensor of shape [64],
        'gru1.weight_ih_l0': tensor of shape [288, 96],
        ...
    }

Each key is "layer_name.parameter_name". The naming convention for built-in
layers is:
    - Conv1d:  "weight" and "bias"
    - GRU:     "weight_ih_l0", "weight_hh_l0", "bias_ih_l0", "bias_hh_l0"
    - Linear:  "weight" and "bias"

The "_l0" suffix means "layer 0" because nn.GRU supports stacking multiple
layers; we use single-layer GRUs so it is always _l0.

THE JSON FORMAT

The output JSON looks like this:

    {
        "format": "nanopitch_v1",
        "cond_size": 64,
        "gru_size": 96,
        "n_mels": 40,
        "pitch_bins": 360,
        "n_weights": 302857,
        "weights": [0.0123, -0.456, 0.789, ...]   <-- ALL weights as one flat list
    }

The browser loads this with fetch() or FileReader, JSON.parse()s it, then
copies the "weights" array into the WASM linear memory (HEAPF32) and calls
nanopitch_load_weights(ptr, n, cond_size, gru_size), which simply assigns
pointers into the flat buffer. No copying on the C side — just pointer
arithmetic.

Layout order (MUST match C's nanopitch_load_weights):
    conv1_weight, conv1_bias,
    conv2_weight, conv2_bias,
    gru1_w_ih, gru1_w_hh, gru1_b_ih, gru1_b_hh,
    gru2_w_ih, gru2_w_hh, gru2_b_ih, gru2_b_hh,
    gru3_w_ih, gru3_w_hh, gru3_b_ih, gru3_b_hh,
    dense_vad_weight, dense_vad_bias,
    dense_pitch_weight, dense_pitch_bias

Conv weights are stored as [out_channels][in_channels][kernel_size]
to match C's row-major indexing.

Usage:
    python export_weights.py checkpoint.pth -o model.json
    python export_weights.py checkpoint.pth -o model.json --quantize uint8
"""

import argparse
import json
import struct
import sys
import os
import warnings

import numpy as np
import torch

# Add the training directory to Python's import path so we can import the
# NanoPitch model class. The model class defines the architecture (which
# layers exist, their sizes, etc.), which is needed to correctly load the
# state_dict from the checkpoint file.
#
# Oct 8 (EC-2a): upstream has this script in `deployment/` with `training/`
# as a root-level sibling, so '..'/'training' resolved correctly there. In
# this repo `training/` is a *child* of the directory holding this script
# (`vendor/nanopitch/training/`), so the original '..' segment pointed at
# `vendor/training` (nonexistent) and raised ImportError. Fixed to resolve
# the sibling-in-place-here layout.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'training'))
from model import NanoPitch


def load_checkpoint(path):
    """Load model from checkpoint, return model and metadata.

    A PyTorch checkpoint (.pth file) is a Python dictionary saved with
    torch.save(). Ours contains:
        - 'state_dict':   the OrderedDict of all weight tensors
        - 'model_kwargs': the constructor arguments (cond_size, gru_size)
                          so we can recreate the exact same architecture

    We load onto CPU (map_location='cpu') because we only need to read the
    numbers — we are not going to run GPU inference here.
    """
    warnings.warn(
        "Loading checkpoint via torch.load() executes Python deserialization. "
        "Only export checkpoints from trusted sources.",
        RuntimeWarning,
    )
    ckpt = torch.load(path, map_location='cpu', weights_only=False)
    kwargs = ckpt.get('model_kwargs', {'cond_size': 64, 'gru_size': 96})
    model = NanoPitch(**kwargs)
    model.load_state_dict(ckpt['state_dict'])
    # model.eval() sets the model to evaluation mode. This disables dropout
    # and batch normalization training behavior. NanoPitch doesn't use those,
    # but it is good practice — and it ensures state_dict values are final.
    model.eval()
    return model, kwargs


def extract_weights_flat(model):
    """Extract all weights as a single flat float32 numpy array.

    === WHY A FLAT ARRAY? ===

    The C inference engine (nanopitch.c) expects all weights packed into one
    contiguous float* buffer. The C function nanopitch_load_weights() walks
    through this buffer with a moving pointer, assigning each section to the
    corresponding layer:

        const float *p = data;
        w->conv1_weight = p;  p += cond_size * 40 * 3;
        w->conv1_bias   = p;  p += cond_size;
        ...

    If we put the weights in the wrong order, or flatten a tensor in the wrong
    memory layout, the C code will read garbage values and the model will
    produce nonsense. This is the most critical part of the export pipeline.

    === ORDER MUST MATCH C's nanopitch_load_weights() ===

    The C code reads weights in this exact order:
        1. conv1 weight + bias
        2. conv2 weight + bias
        3. gru1 (w_ih, w_hh, b_ih, b_hh)
        4. gru2 (w_ih, w_hh, b_ih, b_hh)
        5. gru3 (w_ih, w_hh, b_ih, b_hh)
        6. dense_vad weight + bias
        7. dense_pitch weight + bias
    """
    # model.state_dict() returns an OrderedDict of {name: tensor} pairs.
    # For example:
    #   'conv1.weight'          -> shape [64, 40, 3]
    #   'conv1.bias'            -> shape [64]
    #   'gru1.weight_ih_l0'     -> shape [288, 96]
    #   'dense_pitch.weight'    -> shape [360, 384]
    #   etc.
    sd = model.state_dict()
    arrays = []

    # ── Conv1d Weights ──
    #
    # HOW CONV1D WEIGHTS ARE SHAPED IN PYTORCH:
    #
    # PyTorch's nn.Conv1d(in_channels, out_channels, kernel_size) stores its
    # weight tensor with shape:
    #
    #     [out_channels, in_channels, kernel_size]
    #
    # For conv1 = Conv1d(40, 64, kernel_size=3):
    #     weight shape = [64, 40, 3]
    #     bias shape   = [64]
    #
    # This means: for each of the 64 output filters, there is a 2D kernel of
    # size [40, 3] that slides across the time axis. The 40 corresponds to the
    # 40 mel frequency bands (input channels), and 3 is the temporal receptive
    # field (3 frames = 30ms at 10ms hop).
    #
    # When we call .flatten(), PyTorch uses row-major (C-contiguous) order by
    # default, which means the innermost dimension (kernel_size) varies fastest.
    # This matches C's row-major array indexing:
    #     weight[o][i][k] in C  <==>  weight[o * in_ch * kern + i * kern + k]
    #
    # So .numpy().flatten() produces exactly the memory layout C expects.
    #
    # Conv1: [out_ch=64, in_ch=40, kernel=3] -- already correct for C row-major
    arrays.append(sd['conv1.weight'].numpy().flatten())
    arrays.append(sd['conv1.bias'].numpy().flatten())

    # Conv2: [out_ch=96, in_ch=64, kernel=3]
    arrays.append(sd['conv2.weight'].numpy().flatten())
    arrays.append(sd['conv2.bias'].numpy().flatten())

    # ── GRU Weights ──
    #
    # HOW GRU WEIGHTS ARE ORGANIZED IN PYTORCH:
    #
    # A GRU (Gated Recurrent Unit) has three internal gates:
    #     r = reset gate    (decides how much of the previous hidden state to forget)
    #     z = update gate   (decides how much to update the hidden state)
    #     n = new gate      (the candidate hidden state to blend in)
    #
    # The standard GRU equations are:
    #     r_t = sigmoid(W_ir @ x_t + b_ir + W_hr @ h_{t-1} + b_hr)
    #     z_t = sigmoid(W_iz @ x_t + b_iz + W_hz @ h_{t-1} + b_hz)
    #     n_t = tanh(W_in @ x_t + b_in + r_t * (W_hn @ h_{t-1} + b_hn))
    #     h_t = (1 - z_t) * n_t + z_t * h_{t-1}
    #
    # Rather than storing 6 separate weight matrices (W_ir, W_iz, W_in for
    # input, and W_hr, W_hz, W_hn for hidden), PyTorch concatenates the three
    # gate matrices into two large matrices:
    #
    #     weight_ih = [W_ir]    shape: [3*hidden_size, input_size]
    #                 [W_iz]     (stacked vertically: r, z, n gates)
    #                 [W_in]
    #
    #     weight_hh = [W_hr]    shape: [3*hidden_size, hidden_size]
    #                 [W_hz]
    #                 [W_hn]
    #
    #     bias_ih = [b_ir, b_iz, b_in]   shape: [3*hidden_size]
    #     bias_hh = [b_hr, b_hz, b_hn]   shape: [3*hidden_size]
    #
    # For gru_size=96:
    #     weight_ih shape = [288, 96]   (288 = 3 * 96)
    #     weight_hh shape = [288, 96]
    #     bias_ih shape   = [288]
    #     bias_hh shape   = [288]
    #
    # The "ih" stands for "input-to-hidden" (transforms the input x_t).
    # The "hh" stands for "hidden-to-hidden" (transforms the previous state h_{t-1}).
    #
    # The factor of 3 is because each gate (r, z, n) has its own rows in the
    # concatenated matrix, so the first hidden_size rows are for the reset gate,
    # the next hidden_size rows for the update gate, and the last hidden_size
    # rows for the new gate.
    #
    # The C code uses the same concatenated layout, so we simply flatten these
    # tensors in order. The C GRU implementation splits them back into gates
    # using pointer offsets: rows [0..H) for r, [H..2H) for z, [2H..3H) for n.
    #
    # PyTorch naming convention for GRU parameters:
    #     weight_ih_l0  -->  "input-to-hidden, layer 0"
    #     weight_hh_l0  -->  "hidden-to-hidden, layer 0"
    #     bias_ih_l0    -->  "input bias, layer 0"
    #     bias_hh_l0    -->  "hidden bias, layer 0"
    #
    # We export them in the order: w_ih, w_hh, b_ih, b_hh for each GRU layer.
    # This must match the ASSIGN() macro order in nanopitch.c.
    for gru_name in ['gru1', 'gru2', 'gru3']:
        arrays.append(sd[f'{gru_name}.weight_ih_l0'].numpy().flatten())
        arrays.append(sd[f'{gru_name}.weight_hh_l0'].numpy().flatten())
        arrays.append(sd[f'{gru_name}.bias_ih_l0'].numpy().flatten())
        arrays.append(sd[f'{gru_name}.bias_hh_l0'].numpy().flatten())

    # ── Linear (Dense) Layer Weights ──
    #
    # HOW LINEAR LAYER WEIGHTS MAP TO DENSE LAYERS IN C:
    #
    # PyTorch's nn.Linear(in_features, out_features) stores:
    #     weight: shape [out_features, in_features]
    #     bias:   shape [out_features]
    #
    # The forward pass computes: output = input @ weight.T + bias
    # (Note the transpose — PyTorch stores weight as [out, in], not [in, out].)
    #
    # In C, a dense layer does: for each output neuron o:
    #     output[o] = bias[o] + sum_i(weight[o * in_features + i] * input[i])
    #
    # Since PyTorch's weight is already [out_features, in_features] and we
    # flatten in row-major order, the C code can index it as weight[o][i]
    # which equals weight[o * in_features + i] — a direct match.
    #
    # dense_vad: Linear(384, 1) -- predicts voice activity (voiced or unvoiced)
    #     weight shape = [1, 384]   (384 = gru_size * 4 = concat of conv + 3 GRUs)
    #     bias shape   = [1]
    #
    # dense_pitch: Linear(384, 360) -- predicts pitch as 360-bin posteriorgram
    #     weight shape = [360, 384]
    #     bias shape   = [360]
    #
    # The 384 input features come from concatenating the outputs of:
    #     conv2 output (96) + GRU1 output (96) + GRU2 output (96) + GRU3 output (96)
    #     = 4 * 96 = 384
    arrays.append(sd['dense_vad.weight'].numpy().flatten())
    arrays.append(sd['dense_vad.bias'].numpy().flatten())
    arrays.append(sd['dense_pitch.weight'].numpy().flatten())
    arrays.append(sd['dense_pitch.bias'].numpy().flatten())

    # Concatenate all the individual flat arrays into one giant 1-D array.
    # This is what becomes the "weights" list in the JSON output.
    # The .astype(np.float32) ensures consistent 32-bit precision, matching
    # the C code which uses float (not double) for efficiency.
    return np.concatenate(arrays).astype(np.float32)


def export_json(weights_flat, metadata, output_path):
    """Export weights as JSON with metadata.

    === WHAT THE JSON FILE LOOKS LIKE ===

    {
        "format": "nanopitch_v1",       <-- version tag for future compatibility
        "cond_size": 64,                 <-- conv1 output channels
        "gru_size": 96,                  <-- GRU hidden size
        "n_mels": 40,                    <-- input mel bands
        "pitch_bins": 360,               <-- output pitch classes
        "n_weights": 302857,             <-- total count of float values
        "weights": [0.012, -0.45, ...]   <-- ALL weights as a flat float array
    }

    === HOW THE BROWSER LOADS IT ===

    In the browser (see web/index.html), the loading flow is:

    1. User drops model.json onto the page (or clicks to select file)
    2. JavaScript reads the file with FileReader.readAsText()
    3. JSON.parse() gives us the object with metadata + weights array
    4. We malloc() space in the WASM heap for n_weights * 4 bytes (float32)
    5. We copy each weight into HEAPF32 (the WASM linear memory view):
           for (let i = 0; i < n; i++)
               HEAPF32[(ptr >> 2) + i] = data.weights[i];
    6. We call the C function nanopitch_load_weights(ptr, n, condSize, gruSize)
    7. The C code sets up pointers into this flat buffer for each layer

    The JSON format is human-readable and easy to debug, but larger than binary.
    For production, the binary format (see export_binary below) is ~3x smaller
    because raw float32 bytes are more compact than decimal text + JSON overhead.
    """
    data = {
        'format': 'nanopitch_v1',
        'cond_size': metadata['cond_size'],
        'gru_size': metadata['gru_size'],
        'n_mels': 40,
        'pitch_bins': 360,
        'n_weights': len(weights_flat),
        'weights': weights_flat.tolist(),
    }

    with open(output_path, 'w') as f:
        json.dump(data, f)

    fsize = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Exported {len(weights_flat):,} weights → {output_path} ({fsize:.1f} MB)")


def export_binary(weights_flat, metadata, output_path):
    """Export weights as compact binary format.

    The binary format is more efficient than JSON for deployment:
      - No text encoding overhead (floats stored as raw 4-byte IEEE 754)
      - ~3x smaller file size than JSON
      - Faster to parse (no JSON.parse() needed, just read into ArrayBuffer)

    Binary layout:
        Bytes 0-3:    b'NCWT'  (magic bytes to identify the file format)
        Bytes 4-7:    uint32 version number (currently 1)
        Bytes 8-11:   uint32 cond_size
        Bytes 12-15:  uint32 gru_size
        Bytes 16-19:  uint32 n_weights
        Bytes 20+:    float32[] raw weight data (little-endian)

    All multi-byte values are little-endian ('<' prefix in struct.pack),
    which matches x86/ARM (and therefore WASM, which is always little-endian).
    """
    with open(output_path, 'wb') as f:
        # Header: magic, version, cond_size, gru_size, n_weights
        f.write(b'NCWT')  # magic
        f.write(struct.pack('<I', 1))  # version
        f.write(struct.pack('<I', metadata['cond_size']))
        f.write(struct.pack('<I', metadata['gru_size']))
        f.write(struct.pack('<I', len(weights_flat)))
        # Weights as raw float32
        f.write(weights_flat.tobytes())

    fsize = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Exported {len(weights_flat):,} weights → {output_path} ({fsize:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(
        description="Export NanoPitch weights for WASM deployment")
    parser.add_argument("checkpoint", help="Path to .pth checkpoint")
    parser.add_argument("-o", "--output", required=True,
                        help="Output file (.json or .bin)")
    parser.add_argument("--format", choices=["json", "binary", "auto"],
                        default="auto",
                        help="Output format (default: auto from extension)")
    args = parser.parse_args()

    model, kwargs = load_checkpoint(args.checkpoint)
    weights_flat = extract_weights_flat(model)

    print(f"Model: cond_size={kwargs['cond_size']}, "
          f"gru_size={kwargs['gru_size']}")
    print(f"Total weights: {len(weights_flat):,} "
          f"({len(weights_flat) * 4 / 1024:.1f} KB as float32)")

    fmt = args.format
    if fmt == "auto":
        fmt = "binary" if args.output.endswith(".bin") else "json"

    if fmt == "json":
        export_json(weights_flat, kwargs, args.output)
    else:
        export_binary(weights_flat, kwargs, args.output)


if __name__ == "__main__":
    main()
