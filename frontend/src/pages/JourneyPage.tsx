import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import {
  getJourney,
  postConsent,
  sendJourneyMessage,
  startJourney,
  uploadDocument,
  type JourneyResponse,
} from "../api/client";

type ChatItem = { role: "bot" | "user" | "system"; text: string };

const DOC_CODES = ["IDENTITY_PROOF", "ADDRESS_PROOF", "INCOME_PROOF"] as const;

const PERSONA_HINT =
  "Demo personas: Lakshmi 9876543210 / OTP 123456 · Ramesh 9123456780 / OTP 654321 · Anita 9988776655 / OTP 112233";

export default function JourneyPage() {
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<string>("—");
  const [prompt, setPrompt] = useState<string>("");
  const [input, setInput] = useState("");
  const [chat, setChat] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<Record<string, unknown> | null>(null);
  const [docCode, setDocCode] = useState<string>(DOC_CODES[0]);
  const [last, setLast] = useState<JourneyResponse | null>(null);

  const missingDocs = useMemo(() => {
    const missing = last?.data?.missing_documents;
    return Array.isArray(missing) ? (missing as string[]) : [];
  }, [last]);

  function pushBot(reply: JourneyResponse) {
    setLast(reply);
    setState(reply.state);
    setPrompt(reply.prompt || "");
    setApplicationId(reply.application_id);
    if (reply.access_token) setToken(reply.access_token);
    const lines = [reply.message];
    if (reply.prompt) lines.push(reply.prompt);
    if (reply.error) lines.push(`Error: ${reply.error}`);
    if (reply.expected_format) lines.push(`Expected: ${reply.expected_format}`);
    setChat((prev) => [...prev, { role: "bot", text: lines.filter(Boolean).join("\n") }]);
    const reviewData = reply.data?.review;
    if (reviewData && typeof reviewData === "object") {
      setReview(reviewData as Record<string, unknown>);
    }
    if (reply.state === "SUBMITTED") {
      setReview(null);
    }
  }

  async function onStart() {
    setBusy(true);
    setError(null);
    setChat([]);
    setReview(null);
    try {
      const reply = await startJourney();
      pushBot(reply);
      setChat((prev) => [...prev, { role: "system", text: PERSONA_HINT }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start");
    } finally {
      setBusy(false);
    }
  }

  async function applyReply(reply: JourneyResponse) {
    pushBot(reply);
  }

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!applicationId || !token || !input.trim()) return;
    const text = input.trim();
    setInput("");
    setChat((prev) => [...prev, { role: "user", text }]);
    setBusy(true);
    setError(null);
    try {
      const reply = await sendJourneyMessage(applicationId, token, text);
      await applyReply(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Message failed");
    } finally {
      setBusy(false);
    }
  }

  async function onConsent(granted: boolean) {
    if (!applicationId || !token) return;
    setBusy(true);
    setError(null);
    try {
      const reply = await postConsent(applicationId, token, granted);
      setChat((prev) => [
        ...prev,
        { role: "user", text: granted ? "YES (consent)" : "NO (decline)" },
      ]);
      await applyReply(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Consent failed");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(file: File | null) {
    if (!file || !applicationId || !token) return;
    setBusy(true);
    setError(null);
    setChat((prev) => [
      ...prev,
      { role: "user", text: `Upload ${docCode}: ${file.name}` },
    ]);
    try {
      const reply = await uploadDocument(applicationId, token, docCode, file);
      await applyReply(reply);
      if (reply.data?.missing_documents && Array.isArray(reply.data.missing_documents)) {
        const next = (reply.data.missing_documents as string[])[0];
        if (next) setDocCode(next);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function onRefresh() {
    if (!applicationId || !token) return;
    setBusy(true);
    try {
      const reply = await getJourney(applicationId, token);
      await applyReply(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Refresh failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel journey">
      <div className="journey-header">
        <div>
          <h1>Income Certificate</h1>
          <p className="lede">
            Web text journey (P2). Restricted data stays local. No voice / WhatsApp / IVR yet.
          </p>
        </div>
        <div className="journey-meta">
          <div>
            <span className="label">Application</span>
            <strong>{applicationId ?? "—"}</strong>
          </div>
          <div>
            <span className="label">State</span>
            <strong className="state-pill">{state}</strong>
          </div>
        </div>
      </div>

      <div className="journey-actions">
        <button type="button" onClick={() => void onStart()} disabled={busy}>
          Start application
        </button>
        <button
          type="button"
          className="ghost"
          onClick={() => void onRefresh()}
          disabled={busy || !applicationId}
        >
          Refresh status
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}

      <div className="chat-log">
        {chat.map((item, idx) => (
          <div key={`${item.role}-${idx}`} className={`bubble ${item.role}`}>
            {item.text}
          </div>
        ))}
      </div>

      {state === "CONSENT" && (
        <div className="consent-bar">
          <button type="button" onClick={() => void onConsent(true)} disabled={busy}>
            I agree (consent)
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => void onConsent(false)}
            disabled={busy}
          >
            Decline
          </button>
        </div>
      )}

      {(state === "DOCUMENT_CAPTURE" || state === "DOCUMENT_REJECTED") && (
        <div className="upload-bar">
          <label>
            Document type
            <select value={docCode} onChange={(e) => setDocCode(e.target.value)}>
              {DOC_CODES.map((code) => (
                <option key={code} value={code}>
                  {code}
                  {missingDocs.includes(code) ? " (needed)" : ""}
                </option>
              ))}
            </select>
          </label>
          <input
            type="file"
            accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
            onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
            disabled={busy}
          />
        </div>
      )}

      {review && (
        <article className="card review-card">
          <h2>Review</h2>
          <pre>{JSON.stringify(review, null, 2)}</pre>
          <div className="consent-bar">
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setInput("CONFIRM");
              }}
            >
              Prepare CONFIRM
            </button>
            <button
              type="button"
              className="ghost"
              disabled={busy}
              onClick={() => setInput("CORRECT")}
            >
              Prepare CORRECT
            </button>
          </div>
        </article>
      )}

      <form className="composer" onSubmit={(e) => void onSend(e)}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={prompt || "Type your reply…"}
          disabled={busy || !applicationId}
        />
        <button type="submit" disabled={busy || !applicationId || !input.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
