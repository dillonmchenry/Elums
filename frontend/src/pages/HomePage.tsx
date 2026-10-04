import { useEffect, useState } from "react";
import { healthzApiHealthzGet } from "../client";

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; body: Record<string, unknown> }
  | { kind: "error"; message: string };

export function HomePage() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    healthzApiHealthzGet()
      .then(({ data, error }) => {
        if (error) {
          setHealth({ kind: "error", message: JSON.stringify(error) });
        } else {
          setHealth({ kind: "ok", body: data as Record<string, unknown> });
        }
      })
      .catch((err: unknown) => setHealth({ kind: "error", message: String(err) }));
  }, []);

  return (
    <main>
      <h1>Elums</h1>
      <p data-testid="health-status">
        {health.kind === "loading" && "Checking API health…"}
        {health.kind === "ok" && `API: ${JSON.stringify(health.body)}`}
        {health.kind === "error" && `API unreachable: ${health.message}`}
      </p>
    </main>
  );
}
