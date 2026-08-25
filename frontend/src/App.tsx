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
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            RS
          </span>
          <div>
            <strong>Revenue Services</strong>
            <p>Citizen digital services</p>
          </div>
        </div>
        <nav aria-label="Main">
          <div className="nav-group" role="group" aria-label="Citizen">
            <span className="nav-group-label">Citizen</span>
            <NavLink to="/" end>
              Home
            </NavLink>
            <NavLink to="/journey">Apply</NavLink>
          </div>
          <div className="nav-group" role="group" aria-label="Simulators">
            <span className="nav-group-label">Simulators</span>
            <NavLink to="/whatsapp">WhatsApp</NavLink>
            <NavLink to="/ivr">IVR</NavLink>
          </div>
          <div className="nav-group" role="group" aria-label="Officer">
            <span className="nav-group-label">Officer</span>
            <NavLink to="/officer">Applications</NavLink>
          </div>
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
        Demonstration portal · Data stays local · Not a live government filing system
      </footer>
    </div>
  );
}
