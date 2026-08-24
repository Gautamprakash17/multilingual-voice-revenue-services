import { Link } from "react-router-dom";

const SURFACES = [
  {
    title: "Citizen",
    blurb: "Voice and text certificate applications with guided steps, documents, and payment.",
    status: "Available",
    to: "/journey",
    cta: "Open Apply",
  },
  {
    title: "Channel Simulators",
    blurb: "WhatsApp + IVR demonstration simulators that use the same service journey.",
    status: "Available",
    to: "/whatsapp",
    cta: "Open WhatsApp simulator",
  },
  {
    title: "Officer",
    blurb: "Review applications, approve and issue, request corrections, reject, or escalate.",
    status: "Available",
    to: "/officer",
    cta: "Open Officer review",
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
              {surface.cta} →
            </Link>
          </article>
        ))}
      </div>
      <p className="muted" style={{ marginTop: "1.25rem" }}>
        Also available:{" "}
        <Link to="/ivr">IVR Simulator</Link> for telephone-style keypad and speech practice.
      </p>
    </section>
  );
}
