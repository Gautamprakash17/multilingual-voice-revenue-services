import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  fetchCitizenCertificate,
  fetchServices,
  resumeChannel,
  sendChannelMessage,
  startChannel,
  uploadDocument,
  type JourneyResponse,
  type ServiceDocumentConfig,
} from "../api/client";
import PhoneSimulator from "../components/PhoneSimulator";
import { JOURNEY_COMMANDS } from "../journey/actions";
import { shouldShowPhoneSimulator } from "../journey/phoneSimulator";
import { citizenVisibleText } from "../journey/chatText";
import { stateLabel } from "../journey/labels";
import {
  continueApplicationLabel,
  formatNotificationTime,
  notificationEventLabel,
  notificationSender,
  shouldShowContinueApplication,
  shouldShowViewCertificate,
  simulatedNotificationLabel,
  useCitizenNotifications,
  viewCertificateLabel,
  whatsappChannelLabel,
} from "../journey/citizenNotifications";
import { documentLabel } from "../journey/labels";
import {
  lookupSessionHandoff,
  storeSessionHandoff,
  type WhatsAppResumeNavState,
} from "../journey/sessionHandoff";
import {
  missingSameBrowserHandoffMessage,
  whatsappContinueHint,
} from "../journey/applicationIdentity";
import {
  waComposerAction,
  waMessageInputAutocomplete,
} from "../journey/whatsappComposer";

type Msg = {
  from: "me" | "bot" | "attach";
  text: string;
  at: number;
  attachStatus?: "pending" | "uploaded" | "failed";
  attachMeta?: { filename: string; categoryLabel: string; typeLabel?: string };
};

/**
 * WhatsApp-like simulator — same MessageEnvelope / journey / document upload API.
 * Cross-channel resume uses the existing resume API with X-Session-Token passed
 * internally from Apply (sessionStorage / navigation), never as a citizen field.
 */
export default function WhatsAppSimulatorPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [serviceDocuments, setServiceDocuments] = useState<ServiceDocumentConfig[]>([]);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [applicationId, setApplicationId] = useState("");
  const [token, setToken] = useState("");
  const [resumeAppId, setResumeAppId] = useState("");
  const [state, setState] = useState("—");
  const [language, setLanguage] = useState("en");
  const [otpIssued, setOtpIssued] = useState(false);
  const [authStep, setAuthStep] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missingDocs, setMissingDocs] = useState<string[]>([]);
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [attachDraftOpen, setAttachDraftOpen] = useState(false);
  const [attachType, setAttachType] = useState("");
  const [attachFile, setAttachFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const threadEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messageInputRef = useRef<HTMLInputElement>(null);
  const autoResumeDone = useRef(false);

  useEffect(() => {
    void fetchServices().then((catalog) => {
      const svc =
        catalog.services.find((s) => s.code === "INCOME_CERTIFICATE") ||
        catalog.services[0];
      setServiceDocuments(svc?.documents || []);
    });
  }, []);

  const nextDoc = useMemo(() => {
    const code = missingDocs[0] || "";
    return serviceDocuments.find((d) => d.code === code) || null;
  }, [missingDocs, serviceDocuments]);

  const canAttach =
    Boolean(token) &&
    (state === "DOCUMENT_CAPTURE" || state === "DOCUMENT_REJECTED") &&
    missingDocs.length > 0;

  const composerAction = waComposerAction(input);
  const { items: notices } = useCitizenNotifications(applicationId, token);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, attachDraftOpen, notices.length]);

  useEffect(() => {
    const first = nextDoc?.accepted_types?.[0]?.code || "";
    setAttachType(first);
  }, [nextDoc]);

  useEffect(() => {
    if (!canAttach) {
      setAttachMenuOpen(false);
      setAttachDraftOpen(false);
      setAttachFile(null);
    }
  }, [canAttach]);

  function apply(reply: JourneyResponse, opts?: { skipBotBubble?: boolean }) {
    setApplicationId(reply.application_id);
    if (reply.access_token) {
      setToken(reply.access_token);
      storeSessionHandoff(reply.application_id, reply.access_token);
    }
    setState(reply.state);
    if (reply.language) setLanguage(reply.language);
    const step = typeof reply.data?.auth_step === "string" ? reply.data.auth_step : "";
    setAuthStep(step);
    setOtpIssued(reply.data?.otp_issued === true);
    const missing = reply.data?.missing_documents;
    if (Array.isArray(missing)) {
      setMissingDocs(missing.map(String));
    } else if (reply.state !== "DOCUMENT_CAPTURE" && reply.state !== "DOCUMENT_REJECTED") {
      setMissingDocs([]);
    }
    if (opts?.skipBotBubble) return;
    const text = citizenVisibleText(reply.message || "", reply.prompt);
    if (text) {
      setMessages((m) => [...m, { from: "bot", text, at: Date.now() }]);
    }
  }

  async function doResume(appId: string, sessionToken: string) {
    setBusy(true);
    setError(null);
    try {
      const reply = await resumeChannel(appId, sessionToken, "whatsapp");
      apply(reply, { skipBotBubble: true });
      const serviceText = citizenVisibleText(reply.message || "", reply.prompt);
      setMessages([
        {
          from: "bot",
          text: `Continuing application ${reply.application_id}`,
          at: Date.now(),
        },
        ...(serviceText
          ? [{ from: "bot" as const, text: serviceText, at: Date.now() + 1 }]
          : []),
      ]);
      setResumeAppId("");
    } catch (err) {
      const msg =
        err instanceof Error
          ? err.message
          : "Could not continue this application. Check the Application ID and try again.";
      setError(
        /403|denied|invalid|not found|404/i.test(msg)
          ? "This application could not be continued. It may be invalid or the session is no longer available in this browser. Start again from Apply or IVR, then Continue application."
          : msg,
      );
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (autoResumeDone.current) return;
    const nav = location.state as WhatsAppResumeNavState | null;
    if (nav?.resumeFromWeb && nav.applicationId) {
      autoResumeDone.current = true;
      const handoffToken = lookupSessionHandoff(nav.applicationId);
      if (handoffToken) {
        void doResume(nav.applicationId, handoffToken);
      } else {
        setError(
          "Could not continue securely from Apply. Start the application again and choose Continue on WhatsApp.",
        );
        setResumeAppId(nav.applicationId);
      }
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot handoff on mount
  }, []);

  async function onStart() {
    setBusy(true);
    setError(null);
    setMessages([]);
    setMissingDocs([]);
    setAttachFile(null);
    setAttachDraftOpen(false);
    setAttachMenuOpen(false);
    try {
      apply(await startChannel("whatsapp"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Start failed");
    } finally {
      setBusy(false);
    }
  }

  async function onContinueByAppId() {
    const appId = resumeAppId.trim();
    if (!appId) return;
    const handoffToken = lookupSessionHandoff(appId);
    if (!handoffToken) {
      setError(missingSameBrowserHandoffMessage());
      return;
    }
    await doResume(appId, handoffToken);
  }

  async function sendQuick(text: string) {
    if (!applicationId || !token || uploading) return;
    setMessages((m) => [...m, { from: "me", text, at: Date.now() }]);
    setBusy(true);
    try {
      apply(
        await sendChannelMessage("whatsapp", applicationId, token, {
          text,
          language,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSend(e: FormEvent) {
    e.preventDefault();
    if (!applicationId || !token || !input.trim() || uploading) return;
    const text = input.trim();
    setInput("");
    setAttachMenuOpen(false);
    setMessages((m) => [...m, { from: "me", text, at: Date.now() }]);
    setBusy(true);
    try {
      apply(
        await sendChannelMessage("whatsapp", applicationId, token, {
          text,
          language,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setBusy(false);
    }
  }

  function openDocumentPicker() {
    setAttachMenuOpen(false);
    // Do not open draft until a file is chosen — avoids a permanent form control.
    fileInputRef.current?.click();
  }

  function onFilePicked(file: File | null) {
    if (!file) return;
    setAttachFile(file);
    setAttachDraftOpen(true);
  }

  function clearAttachDraft() {
    setAttachDraftOpen(false);
    setAttachFile(null);
    setAttachMenuOpen(false);
  }

  async function onAttachUpload() {
    if (!applicationId || !token || !attachFile || !nextDoc || uploading) return;
    const accepted = nextDoc.accepted_types || [];
    const typeCode = attachType || accepted[0]?.code;
    if (accepted.length > 0 && !typeCode) {
      setError("Choose a document type before sending.");
      return;
    }
    const categoryLabel = nextDoc.label || documentLabel(nextDoc.code);
    const typeLabel =
      accepted.find((t) => t.code === typeCode)?.label || undefined;
    const filename = attachFile.name;
    setUploading(true);
    setBusy(true);
    setError(null);
    setMessages((m) => [
      ...m,
      {
        from: "attach",
        text: filename,
        at: Date.now(),
        attachStatus: "pending",
        attachMeta: { filename, categoryLabel, typeLabel },
      },
    ]);
    try {
      const reply = await uploadDocument(
        applicationId,
        token,
        nextDoc.code,
        attachFile,
        typeCode,
      );
      setMessages((m) => {
        const next = [...m];
        for (let i = next.length - 1; i >= 0; i -= 1) {
          if (next[i].from === "attach" && next[i].attachStatus === "pending") {
            next[i] = { ...next[i], attachStatus: "uploaded" };
            break;
          }
        }
        return next;
      });
      clearAttachDraft();
      apply(reply);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed. Please try again.";
      setError(msg);
      setMessages((m) => {
        const next = [...m];
        for (let i = next.length - 1; i >= 0; i -= 1) {
          if (next[i].from === "attach" && next[i].attachStatus === "pending") {
            next[i] = { ...next[i], attachStatus: "failed" };
            break;
          }
        }
        return next;
      });
    } finally {
      setUploading(false);
      setBusy(false);
    }
  }

  function formatTime(at: number): string {
    return new Date(at).toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function openIssuedCertificate() {
    if (!applicationId || !token) return;
    void fetchCitizenCertificate(applicationId, token, { download: false })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        window.open(url, "_blank", "noopener,noreferrer");
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Certificate is not available yet.");
      });
  }

  return (
    <section className="panel wa-sim wa-sim-focus">
      <span className="sim-banner" role="status">
        Demonstration simulator — not a live WhatsApp account
      </span>
      <header className="sim-page-head">
        <div>
          <p className="eyebrow">Demonstration</p>
          <h1>WhatsApp</h1>
        </div>
        <p className="sim-page-lede muted">
          Same Application ID across Web, WhatsApp, and IVR.
        </p>
      </header>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      <div className="wa-toolbar wa-toolbar-inline">
        <button
          type="button"
          className="btn-success"
          onClick={() => void onStart()}
          disabled={busy || uploading}
        >
          New chat
        </button>
        {applicationId && <span className="state-pill">{stateLabel(state)}</span>}
        <span className="meta">{applicationId || "No application yet"}</span>
      </div>

      <details className="resume-box resume-box-quiet">
        <summary>Continue an existing application</summary>
        <p className="muted">{whatsappContinueHint()}</p>
        <label htmlFor="wa-resume-app">
          Application ID
          <input
            id="wa-resume-app"
            name="wa-application-id"
            placeholder="INC-xxxx"
            value={resumeAppId}
            onChange={(e) => setResumeAppId(e.target.value)}
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
          />
        </label>
        <button
          type="button"
          onClick={() => void onContinueByAppId()}
          disabled={busy || uploading || !resumeAppId.trim()}
        >
          Continue application
        </button>
      </details>

      {applicationId && token && (
        <PhoneSimulator
          applicationId={applicationId}
          token={token}
          otpActive={shouldShowPhoneSimulator({ state, authStep, otpIssued })}
          onViewCertificate={openIssuedCertificate}
          onContinueApplication={() => {
            messageInputRef.current?.focus();
          }}
        />
      )}

      {state === "AUTHENTICATE" && authStep === "register_offer" && (
        <div className="action-bar-buttons" style={{ marginBottom: "0.75rem" }}>
          <button type="button" className="btn-success" disabled={busy} onClick={() => void sendQuick(JOURNEY_COMMANDS.register)}>
            Register
          </button>
          <button type="button" className="ghost" disabled={busy} onClick={() => void sendQuick(JOURNEY_COMMANDS.anotherNumber)}>
            Use another number
          </button>
        </div>
      )}

      <div className="wa-sim-layout">
      <div className="wa-shell wa-shell-primary">
        <div className="wa-header">
          <strong>Revenue Services</strong>
          <span>
            {applicationId
              ? `${applicationId} · ${stateLabel(state)}`
              : "Start a chat or continue an application"}
          </span>
        </div>
        <div className="wa-thread" role="log" aria-live="polite" aria-relevant="additions">
          {messages.length === 0 && notices.length === 0 && (
            <div className="wa-empty">
              <p className="conversation-empty-title">Start a conversation</p>
              <p>
                Choose <strong>New chat</strong>, or continue an existing application. Status
                updates appear here as messages.
              </p>
            </div>
          )}
          {notices.map((item) => (
            <div
              key={item.id}
              className={`wa-bubble bot wa-notice${
                item.event_type === "ISSUED"
                  ? " wa-notice-issued"
                  : item.event_type === "NEEDS_CORRECTION"
                    ? " wa-notice-correction"
                    : ""
              }`}
            >
              <span className="wa-notice-label">
                {notificationSender()} · {whatsappChannelLabel()}
              </span>
              {item.event_type === "ISSUED" ? (
                <strong className="wa-notice-title">✓ Certificate Issued</strong>
              ) : item.event_type === "NEEDS_CORRECTION" ? (
                <strong className="wa-notice-title">Correction required</strong>
              ) : (
                <strong className="wa-notice-title">
                  {notificationEventLabel(item.event_type)}
                </strong>
              )}
              <span className="wa-bubble-text">{item.message}</span>
              <span className="wa-notice-meta">
                {item.application_id} · {simulatedNotificationLabel()}
              </span>
              {shouldShowViewCertificate(item) && (
                <button type="button" className="wa-notice-action" onClick={openIssuedCertificate}>
                  {viewCertificateLabel()}
                </button>
              )}
              {shouldShowContinueApplication(item) && (
                <button
                  type="button"
                  className="wa-notice-action"
                  onClick={() => messageInputRef.current?.focus()}
                >
                  {continueApplicationLabel()}
                </button>
              )}
              {item.created_at && (
                <time className="wa-bubble-time" dateTime={item.created_at}>
                  {formatNotificationTime(item.created_at)}
                </time>
              )}
            </div>
          ))}
          {messages.map((m, i) =>
            m.from === "attach" && m.attachMeta ? (
              <div
                key={`${m.at}-${i}`}
                className={`wa-bubble me wa-attach-bubble${
                  m.attachStatus === "uploaded" ? " uploaded" : ""
                }`}
              >
                <span className="wa-attach-icon" aria-hidden="true">
                  📄
                </span>
                <div className="wa-attach-body">
                  <strong>{m.attachMeta.filename}</strong>
                  <span>
                    {m.attachMeta.categoryLabel}
                    {m.attachMeta.typeLabel ? ` · ${m.attachMeta.typeLabel}` : ""}
                  </span>
                  <span className="wa-attach-status">
                    {m.attachStatus === "pending" && "Sending…"}
                    {m.attachStatus === "uploaded" && "Uploaded ✓"}
                    {m.attachStatus === "failed" && "Failed — try again"}
                  </span>
                </div>
                <time className="wa-bubble-time" dateTime={new Date(m.at).toISOString()}>
                  {formatTime(m.at)}
                </time>
              </div>
            ) : (
              <div key={`${m.at}-${i}`} className={`wa-bubble ${m.from}`}>
                <span className="wa-bubble-text">{m.text}</span>
                <time className="wa-bubble-time" dateTime={new Date(m.at).toISOString()}>
                  {formatTime(m.at)}
                </time>
              </div>
            ),
          )}
          <div ref={threadEndRef} />
        </div>

        {attachDraftOpen && canAttach && nextDoc && attachFile && (
          <div className="wa-attach-draft" aria-label="Document attachment draft">
            <p className="wa-attach-draft-hint muted">Demo documents only</p>
            <p className="wa-attach-draft-title">
              Document
              <strong>{attachFile.name}</strong>
            </p>
            <p className="meta">
              {nextDoc.label || documentLabel(nextDoc.code)}
            </p>
            {(nextDoc.accepted_types || []).length > 0 && (
              <div className="doc-type-options" role="group" aria-label="Document type">
                <span className="wa-attach-type-label">Type</span>
                {(nextDoc.accepted_types || []).map((t) => (
                  <button
                    key={t.code}
                    type="button"
                    className={attachType === t.code ? "doc-type-btn active" : "doc-type-btn"}
                    aria-pressed={attachType === t.code}
                    disabled={busy || uploading}
                    onClick={() => setAttachType(t.code)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            )}
            <div className="wa-attach-draft-actions">
              <button
                type="button"
                className="ghost"
                disabled={uploading}
                onClick={clearAttachDraft}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={
                  busy ||
                  uploading ||
                  ((nextDoc.accepted_types || []).length > 0 && !attachType)
                }
                onClick={() => void onAttachUpload()}
              >
                {uploading ? "Sending…" : "Send document"}
              </button>
            </div>
          </div>
        )}

        {/* Hidden until 📎 → Document; never shown as a permanent form control */}
        <input
          ref={fileInputRef}
          id="wa-file-picker"
          type="file"
          className="visually-hidden"
          accept=".pdf,.png,.jpg,.jpeg"
          tabIndex={-1}
          aria-label="Choose document file"
          onChange={(e) => {
            onFilePicked(e.target.files?.[0] ?? null);
            e.target.value = "";
          }}
        />

        <form
          className="wa-composer"
          onSubmit={(e) => void onSend(e)}
          autoComplete="off"
        >
          <div className="wa-attach-wrap">
            <button
              type="button"
              className="wa-attach-trigger"
              aria-label={
                canAttach
                  ? "Attach document"
                  : "Attach document (available when documents are required)"
              }
              aria-expanded={attachMenuOpen}
              aria-haspopup="menu"
              disabled={!canAttach || busy || uploading}
              title={
                canAttach
                  ? "Attach a document"
                  : "Document attachment is available when documents are required"
              }
              onClick={() => setAttachMenuOpen((open) => !open)}
            >
              <span aria-hidden="true">📎</span>
            </button>
            {attachMenuOpen && canAttach && (
              <div className="wa-attach-menu" role="menu">
                <button
                  type="button"
                  role="menuitem"
                  aria-controls="wa-file-picker"
                  onClick={openDocumentPicker}
                >
                  Document
                </button>
              </div>
            )}
          </div>

          <label htmlFor="wa-message" className="visually-hidden">
            Message
          </label>
          <input
            ref={messageInputRef}
            id="wa-message"
            name="wa-chat-message"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Type a message…"
            disabled={busy || !token || uploading}
            aria-label="Type a message"
            autoCapitalize="off"
            inputMode="text"
            {...waMessageInputAutocomplete()}
          />

          {composerAction === "send" ? (
            <button
              type="submit"
              className="wa-composer-send"
              disabled={busy || !token || !input.trim() || uploading}
              aria-label="Send message"
            >
              Send
            </button>
          ) : (
            <button
              type="button"
              className="wa-composer-mic"
              disabled={!token || busy || uploading}
              aria-label="Voice messages are not available in this simulator — type a message"
              title="Voice messages are not available in this simulator — type a message"
              onClick={() => messageInputRef.current?.focus()}
            >
              <span aria-hidden="true">🎤</span>
            </button>
          )}
        </form>
      </div>
      </div>
    </section>
  );
}
