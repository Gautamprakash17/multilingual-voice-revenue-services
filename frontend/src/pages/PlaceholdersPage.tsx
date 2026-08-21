const SURFACES = [
  {
    title: "Citizen",
    blurb: "Voice + text certificate journey on the Apply page.",
    status: "Available",
  },
  {
    title: "Channel Simulator",
    blurb: "WhatsApp and IVR simulators behind realistic adapters.",
    status: "Available",
  },
  {
    title: "Officer Dashboard",
    blurb: "Queue, approve, reject, request correction, and escalate with RBAC.",
    status: "Available",
  },
];

export default function PlaceholdersPage() {
  return (
    <section className="panel">
      <h1>Application surfaces</h1>
      <p className="lede">
        Overview of product surfaces in this POC, including citizen apply and officer review.
      </p>
      <div className="grid three">
        {SURFACES.map((surface) => (
          <article key={surface.title} className="card placeholder">
            <h2>{surface.title}</h2>
            <p>{surface.blurb}</p>
            <span className="chip">{surface.status}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
