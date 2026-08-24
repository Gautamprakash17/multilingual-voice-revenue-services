import { Link } from "react-router-dom";
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
      <div className="landing-hero">
        <h1>Revenue Services</h1>
        <p className="lede">
          Apply for government certificates through voice or text. Speak in English, हिन्दी, or
          ಕನ್ನಡ — the service guides you step by step.
        </p>
        <div className="landing-cta">
          <Link to="/journey" className="btn btn-primary-lg">
            Start an application
          </Link>
          <Link to="/placeholders" className="ghost" style={{ display: "inline-flex" }}>
            View service surfaces
          </Link>
        </div>
        <ul className="landing-features">
          <li>
            <strong>Voice + text</strong>
            Speak naturally or type — both use the same secure journey.
          </li>
          <li>
            <strong>English / हिन्दी / ಕನ್ನಡ</strong>
            Choose your preferred language at the start of the application.
          </li>
          <li>
            <strong>Local processing</strong>
            Speech and application data stay on the local platform for this POC.
          </li>
          <li>
            <strong>Track your application</strong>
            Keep your application ID to check status after submission.
          </li>
        </ul>
      </div>

      <details className="system-status section-card">
        <summary>System status</summary>
        {loading && <p className="muted">Checking service availability…</p>}
        {error && (
          <div className="alert error" role="alert">
            <strong>Connection:</strong> offline — {error}
          </div>
        )}
        {!loading && !error && (
          <div className="grid">
            <article className="card">
              <h2>Application service</h2>
              <StatusBadge label="Connectivity" tone="ok" value="Online" />
              <StatusBadge
                label="Liveness"
                tone={health?.status === "ok" ? "ok" : "bad"}
                value={health?.status ?? "unknown"}
              />
              <p className="meta">{health?.service}</p>
              <p className="meta">
                Version {health?.version} · {health?.environment}
              </p>
            </article>
            <article className="card">
              <h2>System readiness</h2>
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
      </details>
    </section>
  );
}
