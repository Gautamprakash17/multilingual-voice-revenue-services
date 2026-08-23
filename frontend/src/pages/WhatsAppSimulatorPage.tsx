import { useState } from "react";
import type { FormEvent } from "react";
import {
  resumeChannel,
  sendChannelMessage,
  startChannel,
  type JourneyResponse,
} from "../api/client";

type Msg = { from: "me" | "bot"; text: string };

/**
 * WhatsApp-like simulator — same MessageEnvelope / journey backend.
 * Resume: paste Application ID + session token from Web to continue.
 */
export default function WhatsAppSimulatorPage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [applicationId, setApplicationId] = useState("");
  const [token, setToken] = useState("");
  const [resumeAppId, setResumeAppId] = useState("");
  const [resumeToken, setResumeToken] = useState("");
  const [state, setState] = useState("—");
  const [language, setLanguage] = useState("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function apply(reply: JourneyResponse) {
    setApplicationId(reply.application_id);
    if (reply.access_token) setToken(reply.access_token);
    setState(reply.state);
    if (reply.language) setLanguage(reply.language);
    const text = [reply.message, reply.prompt].filter(Boolean).join("\n");
    setMessages((m) => [...m, { from: "bot", text }]);
  }

  async function onStart() {
    setBusy(true);
    setError(null);
    setMessages([]);
    try {
      apply(await startChannel("whatsapp"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Start failed");
    } finally {
      setBusy(false);
    }
  }

  async function onResume() {
    if (!resumeAppId || !resumeToken) return;
    setBusy(true);
    setError(null);
    try {
      const reply = await resumeChannel(resumeAppId, resumeToken, "whatsapp");
      apply(reply);
      setMessages((m) => [
        ...m,
        {
          from: "bot",
          text: `Resumed ${reply.application_id} (lang=${reply.language || "—"})`,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Resume failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSend(e: FormEvent) {
    e.preventDefault();
    if (!applicationId || !token || !input.trim()) return;
    const text = input.trim();
    setInput("");
    setMessages((m) => [...m, { from: "me", text }]);
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

  return (
    <section className="panel wa-sim">
      <h1>WhatsApp Simulator</h1>
      <p className="lede">
        Practice the same certificate journey in a WhatsApp-style chat. This is a simulator,
        not a live WhatsApp account. You can resume a web application with its ID and session
        token.
      </p>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      <div className="section-card">
        <div className="journey-actions">
          <button type="button" onClick={() => void onStart()} disabled={busy}>
            New WhatsApp session
          </button>
          <span className="state-pill" aria-label={`State ${state}`}>
            {state}
          </span>
          <span className="meta">{applicationId || "No application yet"}</span>
        </div>
      </div>

      <div className="card resume-box">
        <h2>Resume from web application</h2>
        <label htmlFor="wa-resume-app">
          Application ID
          <input
            id="wa-resume-app"
            placeholder="INC-xxxx"
            value={resumeAppId}
            onChange={(e) => setResumeAppId(e.target.value)}
          />
        </label>
        <label htmlFor="wa-resume-token">
          Session token
          <input
            id="wa-resume-token"
            placeholder="Paste web session token"
            value={resumeToken}
            onChange={(e) => setResumeToken(e.target.value)}
          />
        </label>
        <button type="button" onClick={() => void onResume()} disabled={busy}>
          Resume on WhatsApp
        </button>
      </div>

      <div className="wa-thread" role="log" aria-live="polite">
        {messages.length === 0 && (
          <div className="wa-bubble bot">Start a session or resume from the web Apply page.</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`wa-bubble ${m.from}`}>
            {m.text}
          </div>
        ))}
      </div>

      <form className="composer" onSubmit={(e) => void onSend(e)}>
        <label htmlFor="wa-message" className="visually-hidden">
          WhatsApp message
        </label>
        <input
          id="wa-message"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message…"
          disabled={busy || !token}
          aria-label="WhatsApp message"
        />
        <button type="submit" disabled={busy || !token || !input.trim()}>
          Send
        </button>
      </form>
    </section>
  );
}
