import { defineConfig } from "@hey-api/openapi-ts";

// Regenerate the API client from the committed ../openapi.json (itself
// regenerated with `make openapi`) — see IMPLEMENTATION_PLAN_2026-10-03.md
// M5. Codegen output is gitignored (src/client/) since it's derivable, not
// authored.
export default defineConfig({
  input: "../openapi.json",
  output: "src/client",
  plugins: ["@hey-api/client-fetch"],
});
