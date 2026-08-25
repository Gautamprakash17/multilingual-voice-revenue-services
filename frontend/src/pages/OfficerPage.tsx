import { useCallback, useEffect, useState } from "react";
import {
  fetchOfficerApplication,
  fetchOfficerCertificate,
  fetchOfficerHistory,
  fetchOfficerQueue,
  fetchServices,
  officerAction,
  type OfficerApplication,
  type OfficerHistoryItem,
  type ServiceConfig,
} from "../api/client";
import {
  certificateDemoDisclaimer,
  certificateIssuedTitle,
  certificateReadyCopy,
  issuedCertificateErrorMessage,
  issuedCertificateHeading,
  issuedCertificateLoadingMessage,
  issuedCertificateMissingMessage,
  issuedCertificateUiState,
  isIssuedCertificateDoc,
} from "../officer/certificate";
import {
  formatOfficerActionAt,
  formatOfficerChannel,
  officerApplicantSummary,
  officerHistoryEmptyMessage,
  officerQueueEmptyMessage,
  officerStatusCounts,
  type OfficerListMode,
} from "../officer/labels";
import {
  documentLabel,
  fieldLabel,
  processingStatusBadgeClass,
  processingStatusLabel,
  serviceDisplayName,
  statusLifecycleSteps,
  verificationStatusLabel,
} from "../journey/labels";

const DEFAULT_TOKEN = "officer-poc-token";

export default function OfficerPage() {
  const [token, setToken] = useState(DEFAULT_TOKEN);
  const [mode, setMode] = useState<OfficerListMode>("applications");
  const [queue, setQueue] = useState<OfficerApplication[]>([]);
  const [history, setHistory] = useState<OfficerHistoryItem[]>([]);
  const [services, setServices] = useState<ServiceConfig[]>([]);
  const [selected, setSelected] = useState<OfficerApplication | null>(null);
  const [notes, setNotes] = useState("Please correct annual income");
  const [targetField, setTargetField] = useState("annual_income");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [listLoading, setListLoading] = useState(false);
  const [certBusy, setCertBusy] = useState(false);
  const [certError, setCertError] = useState<string | null>(null);

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
      const catalog = await fetchServices().catch(() => ({ services: [] as ServiceConfig[] }));
      setServices(catalog.services || []);
      await Promise.all([refreshQueue(), refreshHistory()]);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void refresh();
    // Load once when the officer token is available.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function selectHistoryItem(item: OfficerHistoryItem) {
    setBusy(true);
    setCertError(null);
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

  const counts = officerStatusCounts(queue, history);
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

  const certState = issuedCertificateUiState({
    processingStatus: selected?.processing_status,
    certificate: selected?.issued_certificate,
    loading: certBusy,
    error: certError,
  });

  async function openCertificate(download: boolean) {
    if (!selected) return;
    setCertBusy(true);
    setCertError(null);
    try {
      const blob = await fetchOfficerCertificate(token, selected.application_id, {
        download,
      });
      const url = URL.createObjectURL(blob);
      const filename =
        selected.issued_certificate?.filename ||
        `income-certificate-${selected.application_id}.pdf`;
      if (download) {
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.click();
      } else {
        window.open(url, "_blank", "noopener,noreferrer");
      }
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setCertError(err instanceof Error ? err.message : issuedCertificateErrorMessage());
    } finally {
      setCertBusy(false);
    }
  }

  return (
    <section className="panel officer-portal">
      <p className="eyebrow">Operations</p>
      <h1>Officer Portal</h1>
      <p className="lede">
        Review submitted applications. Approve and issue, request corrections, reject, or
        escalate. Completed work stays in History.
      </p>

      <div className="metric-strip" aria-label="Application summary">
        <div className="metric-strip-item metric-pending">
          <span>Pending</span>
          <strong>{counts.pending}</strong>
        </div>
        <div className="metric-strip-item metric-review">
          <span>Under review</span>
          <strong>{counts.underReview}</strong>
        </div>
        <div className="metric-strip-item metric-correction">
          <span>Needs correction</span>
          <strong>{counts.needsCorrection}</strong>
        </div>
        <div className="metric-strip-item metric-issued">
          <span>Issued</span>
          <strong>{counts.issued}</strong>
        </div>
        <div className="metric-strip-item metric-rejected">
          <span>Rejected</span>
          <strong>{counts.rejected}</strong>
        </div>
      </div>

      <details className="officer-access officer-access-compact">
        <summary>Officer access</summary>
        <div className="row gap">
          <label htmlFor="officer-token">
            Access token
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
            Refresh
          </button>
        </div>
      </details>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      <div className="officer-tabs-row">
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
      <button type="button" className="ghost" onClick={() => void refresh()} disabled={busy}>
        Refresh
      </button>
      </div>

      <div className="grid two officer-console">
        <div className="section-card officer-queue-panel">
          <h2>{mode === "history" ? "History" : "Applications queue"}</h2>
          {mode === "applications" && (
            <div className="queue-table-wrap">
              <div className="queue-table-head" aria-hidden="true">
                <span>Application ID</span>
                <span>Service</span>
                <span>Applicant</span>
                <span>Status</span>
                <span>Channel</span>
                <span>Updated</span>
              </div>
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
                    onClick={() => {
                      setCertError(null);
                      setSelected(item);
                    }}
                    aria-pressed={selected?.application_id === item.application_id}
                  >
                    <span className="queue-id">{item.application_id}</span>
                    <span>{serviceDisplayName(item.service_code, services)}</span>
                    <span>{officerApplicantSummary(item.fields_present)}</span>
                    <span>
                      <span className={processingStatusBadgeClass(item.processing_status)}>
                        {processingStatusLabel(item.processing_status)}
                      </span>
                      {item.escalated ? (
                        <span className="badge badge-warning">Escalated</span>
                      ) : null}
                    </span>
                    <span>{formatOfficerChannel(item.channel)}</span>
                    <span>{item.created_at ? formatOfficerActionAt(item.created_at) : "—"}</span>
                  </button>
                </li>
              ))}
              {queueEmpty && <li className="muted empty-copy">{queueEmpty}</li>}
            </ul>
            </div>
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
                    <span className={processingStatusBadgeClass(item.processing_status)}>
                      {processingStatusLabel(item.processing_status)}
                    </span>
                    <span className="history-action">{item.last_action_label}</span>
                    <span className="history-time muted">
                      {formatOfficerActionAt(item.action_at)}
                    </span>
                  </button>
                </li>
              ))}
              {historyEmpty && <li className="muted empty-copy">{historyEmpty}</li>}
            </ul>
          )}
        </div>

        <div className="section-card officer-detail-panel">
          <h2>Application detail</h2>
          {!selected && (
            <div className="officer-detail-empty" role="status">
              <span className="empty-state-icon" aria-hidden="true">
                ◫
              </span>
              <p className="conversation-empty-title">No application selected</p>
              <p className="muted">
                {mode === "history"
                  ? "Choose an application from History to view details and the issued certificate."
                  : "Choose an application from the queue to view applicant details, documents and available actions."}
              </p>
            </div>
          )}
          {selected && (
            <div className="officer-detail-sections">
              <header className="officer-detail-hero">
                <div className="officer-detail-hero-main">
                  <span className="label">Application ID</span>
                  <strong className="app-ref">{selected.application_id}</strong>
                  <span
                    className={`${processingStatusBadgeClass(selected.processing_status)} officer-status-badge`}
                  >
                    {processingStatusLabel(selected.processing_status)}
                  </span>
                  {selected.escalated ? (
                    <span className="badge badge-warning">Escalated</span>
                  ) : null}
                </div>
                <dl className="officer-detail-hero-grid">
                  <div>
                    <dt>Service</dt>
                    <dd>{serviceDisplayName(selected.service_code, services)}</dd>
                  </div>
                  <div>
                    <dt>Applicant</dt>
                    <dd>{officerApplicantSummary(selected.fields_present)}</dd>
                  </div>
                  <div>
                    <dt>Channel</dt>
                    <dd>{formatOfficerChannel(selected.channel)}</dd>
                  </div>
                  <div>
                    <dt>Updated</dt>
                    <dd>
                      {historyMatch?.action_at
                        ? formatOfficerActionAt(historyMatch.action_at)
                        : selected.created_at
                          ? formatOfficerActionAt(selected.created_at)
                          : "—"}
                    </dd>
                  </div>
                </dl>
                {(() => {
                  const track = statusLifecycleSteps(selected.processing_status);
                  return track.length > 0 ? (
                    <ol className="status-track status-track-v" aria-label="Application status">
                      {track.map((step) => (
                        <li
                          key={step.id}
                          className={`status-track-step ${step.phase} status-${step.id.toLowerCase()}`}
                          data-status={step.id}
                        >
                          <span className="status-track-marker" aria-hidden="true" />
                          <span>{step.label}</span>
                        </li>
                      ))}
                    </ol>
                  ) : null;
                })()}
              </header>

              <section className="officer-section">
                <h3>Applicant details</h3>
                {selected.fields_present.length === 0 ? (
                  <p className="muted">No form fields recorded.</p>
                ) : (
                  <ul>
                    {selected.fields_present.map((field) => (
                      <li key={field}>{fieldLabel(field)}</li>
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
                {selected.documents.filter((doc) => !isIssuedCertificateDoc(doc.code)).length ===
                0 ? (
                  <p className="muted">No documents on file.</p>
                ) : (
                  <ul>
                    {selected.documents
                      .filter((doc) => !isIssuedCertificateDoc(doc.code))
                      .map((doc) => (
                      <li key={String(doc.code)}>
                        <strong>{documentLabel(String(doc.code))}</strong>
                        {doc.verification_status
                          ? ` — ${verificationStatusLabel(String(doc.verification_status))}`
                          : ""}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {certState !== "hidden" && (
                <section className="officer-section issued-certificate issued-certificate-prominent" aria-label="Issued certificate">
                  <h3>✓ {issuedCertificateHeading()}</h3>
                  <p className="certificate-kicker">{certificateIssuedTitle()}</p>
                  <p>
                    {certificateReadyCopy(serviceDisplayName(selected.service_code, services))}
                  </p>
                  <p className="demo-badge">{certificateDemoDisclaimer()}</p>
                  <dl className="officer-dl">
                    <dt>Application ID</dt>
                    <dd>{selected.application_id}</dd>
                    <dt>Status</dt>
                    <dd>
                      <span className={processingStatusBadgeClass(selected.processing_status)}>
                        {processingStatusLabel(selected.processing_status)}
                      </span>
                    </dd>
                    <dt>Issue date</dt>
                    <dd>
                      {formatOfficerActionAt(selected.issued_certificate?.issued_at || null)}
                    </dd>
                  </dl>
                  {certState === "loading" && (
                    <p className="muted">{issuedCertificateLoadingMessage()}</p>
                  )}
                  {certState === "missing" && (
                    <p className="muted" role="status">
                      {issuedCertificateMissingMessage()}
                    </p>
                  )}
                  {certState === "error" && (
                    <p className="alert error" role="alert">
                      {certError || issuedCertificateErrorMessage()}
                    </p>
                  )}
                  {certState === "ready" && (
                    <div className="officer-actions">
                      <button
                        type="button"
                        className="ghost"
                        disabled={certBusy}
                        onClick={() => void openCertificate(false)}
                      >
                        View PDF
                      </button>
                      <button
                        type="button"
                        disabled={certBusy}
                        onClick={() => void openCertificate(true)}
                      >
                        Download PDF
                      </button>
                    </div>
                  )}
                </section>
              )}

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
                <section className="officer-section officer-actions-panel">
                  <h3>Available actions</h3>
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
                      aria-describedby="correction-field-hint"
                    />
                    <span id="correction-field-hint" className="field-hint">
                      Internal field key for the correction API · {fieldLabel(targetField)}
                    </span>
                  </label>
                  <div className="officer-actions officer-actions-primary">
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
                      className="ghost btn-correction"
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
                </section>
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
