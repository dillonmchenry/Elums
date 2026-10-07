import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
