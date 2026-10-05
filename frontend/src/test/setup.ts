import "@testing-library/jest-dom/vitest";

// `vitest.config.ts` doesn't set `globals: true`, so @testing-library/react's
// own auto-cleanup-on-afterEach never fires (it only self-registers against a
// global `afterEach`) — multi-test files silently accumulate DOM across
// tests until a query happens to collide (hit directly Mon Oct 5 writing
// LoginPage.test.tsx's two tests, each rendering a form with an "Email"
// label). Explicit per-test cleanup, not a per-file workaround.
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
