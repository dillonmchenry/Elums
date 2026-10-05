import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { loginApiAuthLoginPost } from "../client";

// Mon Oct 5 (L0, IMPLEMENTATION_PLAN_2026-10-05.md). Closes PROGRESS.md's
// Day 2 loose end — HomePage.tsx's upload form needed a session cookie
// that only `curl`/Postman (or a devtools `fetch()`, which didn't work
// as a workaround) could obtain. Posts straight through the generated
// client to /api/auth/login, which already sets the HttpOnly cookie
// (elums/api/routers/auth.py) — no new auth plumbing here, just a form.
//
// Demo credentials are surfaced directly on the page (elums/seed.py)
// rather than assumed knowledge — the tester should not have to know
// they exist.
const DEMO_EMAIL = "dana@elums.demo";
const DEMO_PASSWORD = "elums-demo-2026";

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { data, error: loginError } = await loginApiAuthLoginPost({
        body: { email, password },
      });
      if (loginError || !data) {
        setError("Incorrect email or password.");
        return;
      }
      navigate("/");
    } finally {
      setSubmitting(false);
    }
  }

  function fillDemoCredentials() {
    setEmail(DEMO_EMAIL);
    setPassword(DEMO_PASSWORD);
  }

  return (
    <main>
      <h1>Log in</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Email
          <input
            type="email"
            name="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            name="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        <button type="submit" disabled={submitting}>
          Log in
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      <p data-testid="demo-credentials-hint">
        Try the demo account: <code>{DEMO_EMAIL}</code> / <code>{DEMO_PASSWORD}</code>{" "}
        <button type="button" onClick={fillDemoCredentials}>
          Use demo account
        </button>
      </p>
    </main>
  );
}
