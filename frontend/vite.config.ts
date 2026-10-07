import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // X0/EC-0 (Oct 8): the AudioWorklet + Worker graph needs `?worker&url`
  // imports to resolve to a self-contained ES module chunk, and the
  // WASM ESM import in pitchWorker.ts needs `esnext` — this is the
  // AudioWorklet-vs-Next.js decision §13 already made; these two lines
  // are the entire cost of it (ELUMS_TECHNICAL_APPROACH.md §13).
  worker: {
    format: "es",
  },
  build: {
    target: "esnext",
  },
  server: {
    // Reached only through Caddy's reverse_proxy (see deploy/Caddyfile),
    // which forwards whatever Host header the browser sent — allow any
    // host rather than maintaining an allowlist of tunnel/VM hostnames.
    allowedHosts: true,
    // HMR websocket must be told the public port explicitly: Caddy
    // terminates the browser connection on 8080, not Vite's own 5173.
    hmr: {
      clientPort: 8080,
    },
    // Windows host edits do not emit inotify events across Docker
    // Desktop's bind mount, so Vite never sees them without polling.
    watch: {
      usePolling: true,
      interval: 300,
    },
  },
})
