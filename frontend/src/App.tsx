import { NavLink, Route, Routes } from "react-router-dom";
import HealthPage from "./pages/HealthPage";
import IVRSimulatorPage from "./pages/IVRSimulatorPage";
import JourneyPage from "./pages/JourneyPage";
import OfficerPage from "./pages/OfficerPage";
import PlaceholdersPage from "./pages/PlaceholdersPage";
import WhatsAppSimulatorPage from "./pages/WhatsAppSimulatorPage";

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">RV</span>
          <div>
            <strong>Revenue Voice Services</strong>
            <p>Hackathon POC — Multilingual Voice</p>
          </div>
        </div>
        <nav>
          <NavLink to="/" end>
            Health
          </NavLink>
          <NavLink to="/journey">Apply</NavLink>
          <NavLink to="/officer">Officer</NavLink>
          <NavLink to="/whatsapp">WhatsApp Sim</NavLink>
          <NavLink to="/ivr">IVR Sim</NavLink>
          <NavLink to="/placeholders">Surfaces</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<HealthPage />} />
          <Route path="/journey" element={<JourneyPage />} />
          <Route path="/officer" element={<OfficerPage />} />
          <Route path="/whatsapp" element={<WhatsAppSimulatorPage />} />
          <Route path="/ivr" element={<IVRSimulatorPage />} />
          <Route path="/placeholders" element={<PlaceholdersPage />} />
        </Routes>
      </main>
      <footer>
        Data sovereignty first · Local-first voice/NLU · Channel-agnostic envelope
      </footer>
    </div>
  );
}
