import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import {
  fetchHealth,
  fetchReady,
  fetchServices,
  type HealthResponse,
  type ReadyResponse,
  type ServiceConfig,
} from "../api/client";
import StatusBadge from "../components/StatusBadge";
import { citizenServiceBlurb } from "../journey/labels";
import { peekLatestHandoff } from "../journey/sessionHandoff";

const CHANNELS = [
  {
    title: "Web",
    blurb: "A guided voice-or-text application on this portal.",
    to: "/journey",
    cta: "Apply on web",
    icon: "web",
  },
  {
    title: "WhatsApp",
    blurb: "Continue the same application in a chat-style simulator.",
    to: "/whatsapp",
    cta: "Open WhatsApp",
    icon: "whatsapp",
  },
  {
    title: "IVR",
    blurb: "Use the telephone keypad and spoken answers.",
    to: "/ivr",
    cta: "Open IVR",
    icon: "ivr",
  },
] as const;

const HOW_IT_WORKS = [
  { step: "1", title: "Start application", blurb: "Begin on Web, WhatsApp, or IVR." },
  {
    step: "2",
    title: "Complete verification and details",
    blurb: "Confirm identity, provide details, and upload documents.",
  },
  {
    step: "3",
    title: "Track status and receive certificate",
    blurb: "Follow progress and download your certificate when issued.",
  },
];

function ChannelIcon({ kind }: { kind: (typeof CHANNELS)[number]["icon"] }) {
  if (kind === "web") {
    return (
      <svg className="channel-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path
          fill="currentColor"
          d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9A1.5 1.5 0 0 1 18.5 16H13l-1.5 2.5h1.25a.75.75 0 0 1 0 1.5h-4.5a.75.75 0 0 1 0-1.5H9.5L8 16H5.5A1.5 1.5 0 0 1 4 14.5v-9Zm1.5-.5a.5.5 0 0 0-.5.5v9c0 .28.22.5.5.5H18.5a.5.5 0 0 0 .5-.5v-9a.5.5 0 0 0-.5-.5h-13Z"
        />
      </svg>
    );
  }
  if (kind === "whatsapp") {
    return (
      <svg className="channel-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path
          fill="currentColor"
          d="M12 3.5a8 8 0 0 0-6.9 12.05L4.2 20.1a.75.75 0 0 0 .95.95l4.55-.9A8 8 0 1 0 12 3.5Zm0 1.5a6.5 6.5 0 0 1 5.45 10.04.75.75 0 0 0-.1.72l.05.14-3.2.63a.75.75 0 0 0-.45.27A6.5 6.5 0 0 1 6.9 8.7a.75.75 0 0 0-.27.45l-.63 3.2-.14-.05a.75.75 0 0 0-.72.1A6.48 6.48 0 0 1 12 5Zm-2.4 3.35c.2-.05.42 0 .58.14l.9 1.05c.14.16.17.39.08.58l-.3.62a5.6 5.6 0 0 0 2.45 2.45l.62-.3c.19-.09.42-.06.58.08l1.05.9c.2.17.25.45.12.68l-.35.6a.9.9 0 0 1-.85.4 5.8 5.8 0 0 1-5.35-5.35.9.9 0 0 1 .4-.85l.6-.35c.23-.13.51-.08.68.12Z"
        />
      </svg>
    );
  }
  return (
    <svg className="channel-icon" viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="currentColor"
        d="M8.5 3.75h7a2 2 0 0 1 2 2v12.5a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2V5.75a2 2 0 0 1 2-2Zm0 1.5a.5.5 0 0 0-.5.5v12.5c0 .28.22.5.5.5h7a.5.5 0 0 0 .5-.5V5.75a.5.5 0 0 0-.5-.5h-7Zm2.75 11.5a.75.75 0 0 1 .75-.75h.5a.75.75 0 0 1 0 1.5h-.5a.75.75 0 0 1-.75-.75Z"
      />
    </svg>
  );
}

export default function HealthPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [ready, setReady] = useState<ReadyResponse | null>(null);
  const [readyOk, setReadyOk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [services, setServices] = useState<ServiceConfig[]>([]);
  const [handoffId, setHandoffId] = useState<string | null>(null);

  useEffect(() => {
    setHandoffId(peekLatestHandoff()?.applicationId ?? null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [h, r, catalog] = await Promise.all([
          fetchHealth(),
          fetchReady(),
          fetchServices().catch(() => ({ services: [] as ServiceConfig[] })),
        ]);
        if (cancelled) return;
        setHealth(h);
        setReady(r.data);
        setReadyOk(r.ok);
        setServices(catalog.services || []);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Service is temporarily unavailable");
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
    <section className="panel landing">
      <div className="landing-hero landing-hero-premium">
        <p className="eyebrow">Government digital services</p>
        <h1>Revenue Services</h1>
        <p className="lede landing-lede-channels">
          Apply for government services through{" "}
          <span className="channel-pill-inline">Web</span>
          <span className="channel-sep" aria-hidden="true">
            ·
          </span>
          <span className="channel-pill-inline channel-pill-wa">WhatsApp</span>
          <span className="channel-sep" aria-hidden="true">
            ·
          </span>
          <span className="channel-pill-inline channel-pill-ivr">IVR</span>
        </p>
        <div className="landing-cta">
          <Link to="/journey" className="btn btn-primary-lg btn-cta-primary">
            Start an application
          </Link>
          {handoffId ? (
            <Link to="/journey" className="btn btn-secondary btn-cta-secondary">
              Continue application
            </Link>
          ) : null}
        </div>
        <p className="one-app-strip" role="note">
          <strong>One application</strong> — start on any channel, continue on another. Same
          Application ID, status, and certificate everywhere.
        </p>
      </div>

      <section className="landing-section landing-section-band" aria-labelledby="channels-heading">
        <h2 id="channels-heading">Choose your channel</h2>
        <p className="section-lede muted">
          Three entry points into the same guided journey.
        </p>
        <div className="grid three channel-grid">
          {CHANNELS.map((channel) => (
            <article
              key={channel.title}
              className={`card channel-card channel-card-${channel.icon} surface-card`}
            >
              <div className="channel-card-head">
                <span className="channel-icon-wrap" aria-hidden="true">
                  <ChannelIcon kind={channel.icon} />
                </span>
                <h3>{channel.title}</h3>
              </div>
              <p>{channel.blurb}</p>
              <Link className="surface-link channel-cta" to={channel.to}>
                {channel.cta}
              </Link>
            </article>
          ))}
        </div>
      </section>

      <section className="landing-section" aria-labelledby="how-heading">
        <h2 id="how-heading">How it works</h2>
        <ol className="how-it-works how-it-works-flow">
          {HOW_IT_WORKS.map((item, idx) => (
            <li key={item.step} className="how-it-works-item">
              <span className="how-it-works-step" aria-hidden="true">
                {String(idx + 1).padStart(2, "0")}
              </span>
              <div>
                <strong>{item.title}</strong>
                <p>{item.blurb}</p>
              </div>
              {idx < HOW_IT_WORKS.length - 1 ? (
                <span className="how-it-works-arrow" aria-hidden="true">
                  →
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      </section>

      <section className="landing-section" aria-labelledby="services-heading">
        <h2 id="services-heading">Available services</h2>
        {services.length === 0 && loading && (
          <p className="muted">Loading available services…</p>
        )}
        {services.length === 0 && !loading && (
          <p className="muted">Services will appear here when the catalogue is available.</p>
        )}
        <div className="grid three service-catalog">
          {services.map((service) => (
            <article key={service.code} className="card service-preview surface-card">
              <h3>{service.display_name}</h3>
              <p>{citizenServiceBlurb(service.description)}</p>
              <Link className="surface-link" to="/journey">
                Apply for {service.display_name}
              </Link>
            </article>
          ))}
        </div>
      </section>

      <details className="system-status section-card">
        <summary>System status</summary>
        {loading && <p className="muted">Checking service availability…</p>}
        {error && (
          <div className="alert error" role="alert">
            The portal could not reach the application service. Try again in a moment.
          </div>
        )}
        {!loading && !error && (
          <div className="grid">
            <article className="card">
              <h2>Application service</h2>
              <StatusBadge label="Connectivity" tone="ok" value="Online" />
              <StatusBadge
                label="Availability"
                tone={health?.status === "ok" ? "ok" : "bad"}
                value={health?.status === "ok" ? "Available" : "Unavailable"}
              />
            </article>
            <article className="card">
              <h2>System readiness</h2>
              <StatusBadge
                label="Overall"
                tone={readyOk ? "ok" : "warn"}
                value={readyOk ? "Ready" : "Not ready"}
              />
              <StatusBadge
                label="Records"
                tone={ready?.checks.database === "ok" ? "ok" : "bad"}
                value={ready?.checks.database === "ok" ? "Available" : "Unavailable"}
              />
            </article>
          </div>
        )}
      </details>
    </section>
  );
}
