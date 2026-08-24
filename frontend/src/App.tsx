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
          <span className="brand-mark" aria-hidden="true">
            RV
          </span>
          <div>
            <strong>Revenue Voice Services</strong>
            <p>Multilingual Citizen Services</p>
          </div>
        </div>
        <nav aria-label="Main">
          <NavLink to="/" end>
            Home
          </NavLink>
          <NavLink to="/journey">Apply</NavLink>
          <NavLink to="/officer">Officer</NavLink>
          <NavLink to="/whatsapp">WhatsApp</NavLink>
          <NavLink to="/ivr">IVR</NavLink>
          <NavLink to="/placeholders">Surfaces</NavLink>
        </nav>
      </header>
      <main id="main-content">
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
        Official-style POC · Data stays local · Voice and text citizen services
      </footer>
    </div>
  );
}
