import { client } from "./client/client.gen";

// Not auto-generated — lives outside src/client/ on purpose: that whole
// directory is openapi-ts codegen output and gets wiped/overwritten on
// every `npm run codegen`, including any hand-written file placed inside
// it (hit directly Oct 3 2026, M5: a config.ts living in src/client/ was
// silently deleted by the very next codegen run).
//
// Wires the generated client's base URL to same-origin (empty string),
// so requests go through Caddy's /api/* reverse_proxy — see
// deploy/Caddyfile and ELUMS_TECHNICAL_APPROACH.md §11.6. Never a
// hardcoded host: the ssh -L 8080 tunnel and any future named Cloudflare
// Tunnel both work unmodified because this is relative.
client.setConfig({ baseUrl: "" });
