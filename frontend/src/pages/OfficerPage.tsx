import { useState } from "react";
import {
  fetchOfficerQueue,
  officerAction,
  type OfficerApplication,
} from "../api/client";

const DEFAULT_TOKEN = "officer-poc-token";

export default function OfficerPage() {
  const [token, setToken] = useState(DEFAULT_TOKEN);
  const [queue, setQueue] = useState<OfficerApplication[]>([]);
  const [selected, setSelected] = useState<OfficerApplication | null>(null);
  const [notes, setNotes] = useState("Please correct annual income");
  const [targetField, setTargetField] = useState("annual_income");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setBusy(true);
    setError(null);
    try {
      const rows = await fetchOfficerQueue(token);
      setQueue(rows);
      if (selected) {
        const next = rows.find((r) => r.application_id === selected.application_id);
        setSelected(next || null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load queue");
    } finally {
      setBusy(false);
    }
  }

  async function act(action: "approve" | "reject" | "request-correction" | "escalate") {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await officerAction(token, selected.application_id, action, {
        reason: notes,
        notes,
        target_fields: action === "request-correction" ? [targetField] : [],
      });
      setSelected(updated);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h1>Officer review</h1>
      <p className="lede">
        Review submitted applications, request targeted corrections, approve, reject, or
        escalate. Actions are authorized server-side.
      </p>
      <div className="row gap">
        <label>
          Officer token
          <input value={token} onChange={(e) => setToken(e.target.value)} />
        </label>
        <button type="button" onClick={() => void refresh()} disabled={busy}>
          Refresh queue
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="grid two">
        <div>
          <h2>Queue</h2>
          <ul className="queue-list">
            {queue.map((item) => (
              <li key={item.application_id}>
                <button
                  type="button"
                  className={selected?.application_id === item.application_id ? "active" : ""}
                  onClick={() => setSelected(item)}
                >
                  {item.application_id} · {item.processing_status}
                  {item.escalated ? " · escalated" : ""}
                </button>
              </li>
            ))}
            {queue.length === 0 && <li>No applications requiring review.</li>}
          </ul>
        </div>
        <div>
          <h2>Detail</h2>
          {!selected && <p>Select an application.</p>}
          {selected && (
            <>
              <pre className="code-block">
                {JSON.stringify(
                  {
                    application_id: selected.application_id,
                    processing_status: selected.processing_status,
                    journey_state: selected.journey_state,
                    payment_ref: selected.payment_ref,
                    documents: selected.documents,
                    fields_present: selected.fields_present,
                    correction_notes: selected.correction_notes,
                    escalated: selected.escalated,
                  },
                  null,
                  2,
                )}
              </pre>
              <label>
                Notes / reason
                <input value={notes} onChange={(e) => setNotes(e.target.value)} />
              </label>
              <label>
                Correction field
                <input value={targetField} onChange={(e) => setTargetField(e.target.value)} />
              </label>
              <div className="row gap wrap">
                <button type="button" disabled={busy} onClick={() => void act("approve")}>
                  Approve → Issue
                </button>
                <button type="button" disabled={busy} onClick={() => void act("request-correction")}>
                  Request correction
                </button>
                <button type="button" disabled={busy} onClick={() => void act("reject")}>
                  Reject
                </button>
                <button type="button" disabled={busy} onClick={() => void act("escalate")}>
                  Escalate
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
