const SURFACES = [
  {
    title: "Citizen",
    blurb: "Voice + text certificate journey (planned for later phases).",
  },
  {
    title: "Channel Simulator",
    blurb: "WhatsApp / IVR simulators behind realistic adapters (P2+).",
  },
  {
    title: "Officer Dashboard",
    blurb: "Applications, escalations, boundary audit (P2+).",
  },
];

export default function PlaceholdersPage() {
  return (
    <section className="panel">
      <h1>Application surfaces</h1>
      <p className="lede">
        Placeholder sections only. No business functionality in P1.
      </p>
      <div className="grid three">
        {SURFACES.map((surface) => (
          <article key={surface.title} className="card placeholder">
            <h2>{surface.title}</h2>
            <p>{surface.blurb}</p>
            <span className="chip">Coming later</span>
          </article>
        ))}
      </div>
    </section>
  );
}
