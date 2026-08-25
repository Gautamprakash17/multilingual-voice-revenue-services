import { Link } from "react-router-dom";

const SURFACES = [
  {
    title: "Citizen application",
    blurb: "Start or continue a guided certificate application by voice or text.",
    status: "Available",
    to: "/journey",
    cta: "Open Apply",
  },
  {
    title: "WhatsApp simulator",
    blurb: "The same application in a chat-style demonstration.",
    status: "Available",
    to: "/whatsapp",
    cta: "Open WhatsApp",
  },
  {
    title: "Officer portal",
    blurb: "Review applications, issue certificates, request corrections, or reject.",
    status: "Available",
    to: "/officer",
    cta: "Open Officer portal",
  },
];

export default function PlaceholdersPage() {
  return (
    <section className="panel">
      <h1>Service surfaces</h1>
      <p className="lede">
        Citizen, channel, and officer surfaces available in this demonstration.
      </p>
      <div className="grid three">
        {SURFACES.map((surface) => (
          <article key={surface.title} className="card surface-card">
            <h2>{surface.title}</h2>
            <p>{surface.blurb}</p>
            <span className="chip">{surface.status}</span>
            <Link className="surface-link" to={surface.to}>
              {surface.cta}
            </Link>
          </article>
        ))}
      </div>
      <p className="muted" style={{ marginTop: "1.25rem" }}>
        Also available: <Link to="/ivr">IVR simulator</Link> for telephone-style keypad and
        speech practice.
      </p>
    </section>
  );
}
