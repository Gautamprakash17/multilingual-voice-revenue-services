import { useEffect, useState } from "react";
import { fetchHealth, fetchReady, type HealthResponse, type ReadyResponse } from "../api/client";
import StatusBadge from "../components/StatusBadge";

export default function HealthPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [ready, setReady] = useState<ReadyResponse | null>(null);
  const [readyOk, setReadyOk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [h, r] = await Promise.all([fetchHealth(), fetchReady()]);
        if (cancelled) return;
        setHealth(h);
        setReady(r.data);
        setReadyOk(r.ok);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "API unreachable");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="panel">
      <h1>Platform health</h1>
      <p className="lede">
        P1 foundation connectivity check. Business journeys are not implemented yet.
      </p>

      {loading && <p className="muted">Checking API…</p>}
      {error && (
        <div className="alert error">
          <strong>API connectivity:</strong> offline — {error}
        </div>
      )}

      {!loading && !error && (
        <div className="grid">
          <article className="card">
            <h2>API</h2>
            <StatusBadge label="Connectivity" tone="ok" value="online" />
            <StatusBadge
              label="Liveness"
              tone={health?.status === "ok" ? "ok" : "bad"}
              value={health?.status ?? "unknown"}
            />
            <p className="meta">{health?.service}</p>
            <p className="meta">v{health?.version} · {health?.environment}</p>
          </article>
          <article className="card">
            <h2>Readiness</h2>
            <StatusBadge
              label="Overall"
              tone={readyOk ? "ok" : "warn"}
              value={ready?.status ?? "unknown"}
            />
            <StatusBadge
              label="Database"
              tone={ready?.checks.database === "ok" ? "ok" : "bad"}
              value={ready?.checks.database ?? "unknown"}
            />
          </article>
        </div>
      )}
    </section>
  );
}
