import { useCallback, useState } from "react";
import {
  fetchOfficerApplication,
  fetchOfficerHistory,
  fetchOfficerQueue,
  officerAction,
  type OfficerApplication,
  type OfficerHistoryItem,
} from "../api/client";
import {
  formatOfficerActionAt,
  officerHistoryEmptyMessage,
  officerQueueEmptyMessage,
  type OfficerListMode,
} from "../officer/labels";

const DEFAULT_TOKEN = "officer-poc-token";

function statusBadgeClass(status: string): string {
  const s = status.toUpperCase();
  if (s === "ISSUED" || s === "APPROVED") return "badge badge-success";
  if (s === "REJECTED") return "badge badge-error";
  if (s === "NEEDS_CORRECTION" || s.includes("ESCALAT")) return "badge badge-warning";
  return "badge badge-info";
}

function serviceName(code: string): string {
  return code.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function OfficerPage() {
  const [token, setToken] = useState(DEFAULT_TOKEN);
  const [mode, setMode] = useState<OfficerListMode>("applications");
  const [queue, setQueue] = useState<OfficerApplication[]>([]);
  const [history, setHistory] = useState<OfficerHistoryItem[]>([]);
  const [selected, setSelected] = useState<OfficerApplication | null>(null);
  const [notes, setNotes] = useState("Please correct annual income");
  const [targetField, setTargetField] = useState("annual_income");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [listLoading, setListLoading] = useState(false);

  const refreshQueue = useCallback(async () => {
    setListLoading(true);
    setError(null);
    try {
      const rows = await fetchOfficerQueue(token);
      setQueue(rows);
      if (selected && mode === "applications") {
        const next = rows.find((r) => r.application_id === selected.application_id);
        setSelected(next || null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load queue");
    } finally {
      setListLoading(false);
    }
  }, [token, selected, mode]);

  const refreshHistory = useCallback(async () => {
    setListLoading(true);
    setError(null);
    try {
      const rows = await fetchOfficerHistory(token);
      setHistory(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load history");
    } finally {
      setListLoading(false);
    }
  }, [token]);

  async function refresh() {
    setBusy(true);
    try {
      if (mode === "history") {
        await refreshHistory();
      } else {
        await refreshQueue();
      }
    } finally {
      setBusy(false);
    }
  }

  async function selectHistoryItem(item: OfficerHistoryItem) {
    setBusy(true);
    setError(null);
    try {
      const detail = await fetchOfficerApplication(token, item.application_id);
      setSelected(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load application");
    } finally {
      setBusy(false);
    }
  }

  async function switchMode(next: OfficerListMode) {
    setMode(next);
    setSelected(null);
    setBusy(true);
    try {
      if (next === "history") {
        await refreshHistory();
      } else {
        await refreshQueue();
      }
    } finally {
      setBusy(false);
    }
  }

  async function act(action: "approve" | "reject" | "request-correction" | "escalate") {
    if (!selected) return;
    if (action === "reject" || action === "escalate") {
      const ok = window.confirm(
        action === "reject"
          ? "Reject this application? This cannot be undone from the queue."
          : "Escalate this application to a senior officer?",
      );
      if (!ok) return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await officerAction(token, selected.application_id, action, {
        reason: notes,
        notes,
        target_fields: action === "request-correction" ? [targetField] : [],
      });
      setSelected(updated);
      await refreshQueue();
      if (action === "approve" || action === "reject" || action === "escalate") {
        await refreshHistory();
        if (action === "approve" || action === "reject") {
          setMode("history");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  const queueEmpty = officerQueueEmptyMessage(queue.length, listLoading && mode === "applications");
  const historyEmpty = officerHistoryEmptyMessage(
    history.length,
    listLoading && mode === "history",
  );
  const showActions =
    mode === "applications" &&
    selected &&
    ["SUBMITTED", "UNDER_REVIEW", "NEEDS_CORRECTION"].includes(selected.processing_status);

  const historyMatch = selected
    ? history.find((h) => h.application_id === selected.application_id)
    : undefined;

  return (
    <section className="panel">
      <h1>Officer review</h1>
      <p className="lede">
        Review submitted applications. Approve and issue, request corrections, reject, or
        escalate. Completed actions stay in History.
      </p>

      <div className="section-card">
        <div className="row gap">
          <label htmlFor="officer-token">
            Officer access token
            <input
              id="officer-token"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              autoComplete="off"
              aria-describedby="officer-token-hint"
            />
            <span id="officer-token-hint" className="field-hint">
              Required for queue, history, and actions
            </span>
          </label>
          <button type="button" onClick={() => void refresh()} disabled={busy}>
            {mode === "history" ? "Refresh history" : "Refresh queue"}
          </button>
        </div>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      <div className="officer-tabs" role="tablist" aria-label="Officer lists">
        <button
          type="button"
          role="tab"
          aria-selected={mode === "applications"}
          className={mode === "applications" ? "officer-tab active" : "officer-tab"}
          onClick={() => void switchMode("applications")}
          disabled={busy}
        >
          Applications
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === "history"}
          className={mode === "history" ? "officer-tab active" : "officer-tab"}
          onClick={() => void switchMode("history")}
          disabled={busy}
        >
          History
        </button>
      </div>

      <div className="grid two">
        <div className="section-card">
          <h2>{mode === "history" ? "History" : "Applications queue"}</h2>
          {mode === "applications" && (
            <ul className="queue-list">
              {queue.map((item) => (
                <li key={item.application_id}>
                  <button
                    type="button"
                    className={
                      selected?.application_id === item.application_id
                        ? "active queue-row"
                        : "queue-row"
                    }
                    onClick={() => setSelected(item)}
                    aria-pressed={selected?.application_id === item.application_id}
                  >
                    <span>{item.application_id}</span>
                    <span className={statusBadgeClass(item.processing_status)}>
                      {item.processing_status}
                    </span>
                    {item.escalated ? (
                      <span className="badge badge-warning">Escalated</span>
                    ) : null}
                    <span className="queue-row-meta">
                      {serviceName(item.service_code)}
                      {item.created_at ? ` · ${formatOfficerActionAt(item.created_at)}` : ""}
                    </span>
                  </button>
                </li>
              ))}
              {queueEmpty && <li className="muted">{queueEmpty}</li>}
            </ul>
          )}
          {mode === "history" && (
            <ul className="queue-list history-list">
              {history.map((item) => (
                <li key={`${item.application_id}-${item.last_action}-${item.action_at}`}>
                  <button
                    type="button"
                    className={
                      selected?.application_id === item.application_id
                        ? "active history-item"
                        : "history-item"
                    }
                    onClick={() => void selectHistoryItem(item)}
                    aria-pressed={selected?.application_id === item.application_id}
                  >
                    <span className="history-id">{item.application_id}</span>
                    <span className="history-service">{item.service_display_name}</span>
                    <span className={statusBadgeClass(item.processing_status)}>
                      {item.processing_status}
                    </span>
                    <span className="history-action">{item.last_action_label}</span>
                    <span className="history-time muted">
                      {formatOfficerActionAt(item.action_at)}
                    </span>
                  </button>
                </li>
              ))}
              {historyEmpty && <li className="muted">{historyEmpty}</li>}
            </ul>
          )}
        </div>

        <div className="section-card">
          <h2>Application detail</h2>
          {!selected && (
            <p className="muted">
              {mode === "history"
                ? "Select an application from History."
                : "Select an application from the queue."}
            </p>
          )}
          {selected && (
            <div className="officer-detail-sections">
              <section className="officer-section">
                <h3>Application summary</h3>
                <dl className="officer-dl">
                  <dt>Application ID</dt>
                  <dd>{selected.application_id}</dd>
                  <dt>Service</dt>
                  <dd>{serviceName(selected.service_code)}</dd>
                  <dt>Processing status</dt>
                  <dd>
                    <span className={statusBadgeClass(selected.processing_status)}>
                      {selected.processing_status}
                    </span>
                  </dd>
                  <dt>Journey state</dt>
                  <dd>
                    <span className="badge">{selected.journey_state}</span>
                  </dd>
                  <dt>Language</dt>
                  <dd>{selected.language || "—"}</dd>
                  <dt>Escalated</dt>
                  <dd>{selected.escalated ? "Yes" : "No"}</dd>
                </dl>
              </section>

              <section className="officer-section">
                <h3>Form information</h3>
                {selected.fields_present.length === 0 ? (
                  <p className="muted">No form fields recorded.</p>
                ) : (
                  <ul>
                    {selected.fields_present.map((field) => (
                      <li key={field}>{field.replace(/_/g, " ")}</li>
                    ))}
                  </ul>
                )}
                {selected.correction_notes && (
                  <p>
                    <strong>Notes:</strong> {selected.correction_notes}
                  </p>
                )}
              </section>

              <section className="officer-section">
                <h3>Documents</h3>
                {selected.documents.length === 0 ? (
                  <p className="muted">No documents on file.</p>
                ) : (
                  <ul>
                    {selected.documents.map((doc) => (
                      <li key={String(doc.code)}>
                        <strong>{String(doc.code).replace(/_/g, " ")}</strong>
                        {doc.verification_status
                          ? ` — ${String(doc.verification_status)}`
                          : ""}
                        {doc.mime_type ? ` · ${String(doc.mime_type)}` : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section className="officer-section">
                <h3>Payment</h3>
                <dl className="officer-dl">
                  <dt>Payment completed</dt>
                  <dd>{selected.payment_completed ? "Yes" : "No"}</dd>
                  <dt>Payment reference</dt>
                  <dd>{selected.payment_ref || "—"}</dd>
                </dl>
              </section>

              {(historyMatch || mode === "history") && (
                <section className="officer-section">
                  <h3>Activity</h3>
                  <dl className="officer-dl">
                    <dt>Last officer action</dt>
                    <dd>{historyMatch?.last_action_label || "—"}</dd>
                    <dt>Action time</dt>
                    <dd>
                      {historyMatch?.action_at
                        ? formatOfficerActionAt(historyMatch.action_at)
                        : "—"}
                    </dd>
                  </dl>
                </section>
              )}

              {showActions && (
                <>
                  <label htmlFor="officer-notes">
                    Notes / reason
                    <input
                      id="officer-notes"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                    />
                  </label>
                  <label htmlFor="correction-field">
                    Correction field
                    <input
                      id="correction-field"
                      value={targetField}
                      onChange={(e) => setTargetField(e.target.value)}
                    />
                  </label>
                  <div className="officer-actions">
                    <button
                      type="button"
                      className="btn-success"
                      disabled={busy}
                      onClick={() => void act("approve")}
                    >
                      Approve and issue
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      disabled={busy}
                      onClick={() => void act("request-correction")}
                    >
                      Request correction
                    </button>
                    <button
                      type="button"
                      className="btn-danger"
                      disabled={busy}
                      onClick={() => void act("reject")}
                    >
                      Reject
                    </button>
                    <button
                      type="button"
                      className="btn-warning"
                      disabled={busy}
                      onClick={() => void act("escalate")}
                    >
                      Escalate
                    </button>
                  </div>
                </>
              )}

              {mode === "history" && (
                <p className="muted">
                  Viewing a completed application from History. Switch to Applications to act
                  on items still in the review queue.
                </p>
              )}

              <div className="officer-tech">
                <details>
                  <summary>Technical details</summary>
                  <pre className="code-block">
                    {JSON.stringify(
                      {
                        application_id: selected.application_id,
                        service_code: selected.service_code,
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
                </details>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
