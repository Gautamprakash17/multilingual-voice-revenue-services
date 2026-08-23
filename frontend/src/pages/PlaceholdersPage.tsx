const SURFACES = [
  {
    title: "Citizen",
    blurb: "Voice and text certificate applications on the Apply page.",
    status: "Available",
  },
  {
    title: "Channel Simulator",
    blurb: "WhatsApp and IVR simulators using the same service journey.",
    status: "Available",
  },
  {
    title: "Officer Dashboard",
    blurb: "Queue, approve, reject, request correction, and escalate.",
    status: "Available",
  },
];

export default function PlaceholdersPage() {
  return (
    <section className="panel">
      <h1>Service surfaces</h1>
      <p className="lede">
        Overview of citizen, channel, and officer surfaces available in this demonstration.
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
