import { NavLink, Route, Routes } from "react-router-dom";
import HealthPage from "./pages/HealthPage";
import JourneyPage from "./pages/JourneyPage";
import PlaceholdersPage from "./pages/PlaceholdersPage";

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">RV</span>
          <div>
            <strong>Revenue Voice Services</strong>
            <p>Hackathon POC — P2 Income Certificate</p>
          </div>
        </div>
        <nav>
          <NavLink to="/" end>
            Health
          </NavLink>
          <NavLink to="/journey">Apply</NavLink>
          <NavLink to="/placeholders">Surfaces</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HealthPage />} />
          <Route path="/journey" element={<JourneyPage />} />
          <Route path="/placeholders" element={<PlaceholdersPage />} />
        </Routes>
      </main>
      <footer>
        Data sovereignty first · Local-first processing · Modular monolith
      </footer>
    </div>
  );
}
