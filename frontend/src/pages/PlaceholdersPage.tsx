const SURFACES = [
  {
    title: "Citizen",
    blurb: "Voice + text certificate journey on the Apply page.",
  },
  {
    title: "Channel Simulator",
    blurb: "WhatsApp and IVR simulators behind realistic adapters.",
  },
  {
    title: "Officer Dashboard",
    blurb: "Applications, escalations, and boundary audit — planned extension.",
  },
];

export default function PlaceholdersPage() {
  return (
    <section className="panel">
      <h1>Application surfaces</h1>
      <p className="lede">
        Overview of product surfaces. Officer tooling remains an optional extension.
      </p>
      <div className="grid three">
        {SURFACES.map((surface) => (
          <article key={surface.title} className="card placeholder">
            <h2>{surface.title}</h2>
            <p>{surface.blurb}</p>
            <span className="chip">
              {surface.title === "Officer Dashboard" ? "Planned" : "Available"}
            </span>
          </article>
        ))}
      </div>
    </section>
  );
}
