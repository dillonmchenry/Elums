// Minimal AudioWorkletGlobalScope ambient declarations.
//
// TypeScript's bundled "DOM" lib does not include the AudioWorklet
// global-scope types (`AudioWorkletProcessor`, `registerProcessor`,
// `sampleRate`, `currentFrame`, `currentTime`) — those only exist
// inside the worklet's own realm, which is neither the window nor a
// Worker. Rather than pull in a whole-lib third-party types package
// for four symbols, declare exactly what capture-worklet.ts uses.

declare class AudioWorkletProcessor {
  readonly port: MessagePort;
  constructor(options?: AudioWorkletNodeOptions);
  process(
    inputs: Float32Array[][],
    outputs: Float32Array[][],
    parameters: Record<string, Float32Array>,
  ): boolean;
}

declare function registerProcessor(
  name: string,
  processorCtor: (new (options: AudioWorkletNodeOptions) => AudioWorkletProcessor) & {
    parameterDescriptors?: AudioParamDescriptor[];
  },
): void;

declare const sampleRate: number;
declare const currentFrame: number;
declare const currentTime: number;

// Vite's `?worker&url` import suffix (§13/EC-0's own instruction for
// getting an AudioWorklet module through the bundler) resolves to a
// URL string at build time; `vite/client`'s own ambient types don't
// cover this specific query-suffix combination.
declare module "*?worker&url" {
  const url: string;
  export default url;
}
