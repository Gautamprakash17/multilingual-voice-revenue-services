import { useEffect, useRef, useState } from "react";
import {
  sendChannelMessage,
  startChannel,
  type JourneyResponse,
} from "../api/client";

const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"];

function playAudio(b64?: string | null, mime?: string | null) {
  if (!b64) return;
  void new Audio(`data:${mime || "audio/wav"};base64,${b64}`).play().catch(() => undefined);
}

type LogEntry = { kind: "bot" | "prompt" | "dtmf" | "speech" | "system"; text: string };

export default function IVRSimulatorPage() {
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState("—");
  const [prompt, setPrompt] = useState("");
  const [buffer, setBuffer] = useState("");
  const [log, setLog] = useState<LogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [speech, setSpeech] = useState("");
  const [error, setError] = useState<string | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const inCall = Boolean(token && applicationId);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log]);

  function apply(reply: JourneyResponse) {
    setApplicationId(reply.application_id);
    if (reply.access_token) setToken(reply.access_token);
    setState(reply.state);
    setPrompt(reply.prompt || reply.message);
    setLog((l) => {
      const next: LogEntry[] = [...l, { kind: "bot", text: reply.message }];
      if (reply.prompt) next.push({ kind: "prompt", text: reply.prompt });
      return next;
    });
    playAudio(reply.audio_b64, reply.audio_mime);
  }

  async function onCall() {
    setBusy(true);
    setError(null);
    setLog([]);
    setBuffer("");
    try {
      apply(await startChannel("ivr"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Call failed");
    } finally {
      setBusy(false);
    }
  }

  function onEndCall() {
    setApplicationId(null);
    setToken(null);
    setState("—");
    setPrompt("");
    setBuffer("");
    setSpeech("");
    setLog((l) => [...l, { kind: "system", text: "Call ended" }]);
  }

  async function sendDtmf(value: string) {
    if (!applicationId || !token) return;
    setBusy(true);
    setLog((l) => [...l, { kind: "dtmf", text: value }]);
    try {
      apply(
        await sendChannelMessage("ivr", applicationId, token, {
          modality: "dtmf",
          dtmf: value,
        }),
      );
      setBuffer("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "DTMF failed");
    } finally {
      setBusy(false);
    }
  }

  async function sendSpeech() {
    if (!applicationId || !token || !speech.trim()) return;
    setBusy(true);
    setLog((l) => [...l, { kind: "speech", text: speech.trim() }]);
    try {
      apply(
        await sendChannelMessage("ivr", applicationId, token, {
          modality: "voice",
          transcript: speech.trim(),
        }),
      );
      setSpeech("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Speech failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel ivr-sim">
      <span className="sim-banner" role="status">
        Demonstration simulator — not a live phone line
      </span>
      <h1>IVR Simulator</h1>
      <p className="lede">
        Telephone-style keypad and simulated speech for the same certificate journey.
      </p>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      <div className="section-card">
        <div className="call-status-bar">
          <div>
            <p className="call-status-label">
              Call status:{" "}
              <strong>{inCall ? "In call" : "Idle"}</strong>
            </p>
            <p className="meta">
              {applicationId ?? "No call yet"} · state {state}
            </p>
          </div>
          <div className="journey-actions">
            <button
              type="button"
              className="btn-success"
              onClick={() => void onCall()}
              disabled={busy}
            >
              Start call
            </button>
            <button
              type="button"
              className="btn-danger"
              onClick={onEndCall}
              disabled={!inCall && !applicationId}
            >
              End call
            </button>
          </div>
        </div>
        <p className="prompt-line" aria-live="polite">
          {prompt || "Press Start call to begin"}
        </p>
        {state === "DOCUMENT_CAPTURE" && applicationId && (
          <div className="ivr-doc-continue" role="status">
            <p>
              Documents cannot be uploaded by phone. Continue on the web Apply page or WhatsApp
              Simulator using application ID <strong>{applicationId}</strong> and your session
              token.
            </p>
          </div>
        )}
      </div>

      <div className="ivr-layout">
        <div className="phone" aria-label="Telephone keypad">
          <div className="phone-screen" aria-live="polite">
            {buffer || "—"}
          </div>
          <div className="keypad">
            {KEYS.map((k) => (
              <button
                key={k}
                type="button"
                disabled={busy || !token}
                onClick={() => setBuffer((b) => b + k)}
                aria-label={`Key ${k}`}
              >
                {k}
              </button>
            ))}
          </div>
          <div className="journey-actions">
            <button
              type="button"
              disabled={busy || !token || !buffer}
              onClick={() => void sendDtmf(buffer)}
            >
              Send DTMF
            </button>
            <button
              type="button"
              className="ghost"
              onClick={() => setBuffer("")}
              disabled={!buffer}
            >
              Clear
            </button>
          </div>
        </div>

        <div className="ivr-side">
          <div className="section-card ivr-speech-card">
            <h2>Simulated speech</h2>
            <p className="muted">Type what the caller would say, then press Speak.</p>
            <div className="composer">
              <label htmlFor="ivr-speech" className="visually-hidden">
                Simulated speech
              </label>
              <input
                id="ivr-speech"
                value={speech}
                onChange={(e) => setSpeech(e.target.value)}
                placeholder="e.g. en, YES, CONFIRM"
                disabled={busy || !token}
                aria-label="Simulated speech"
              />
              <button
                type="button"
                disabled={busy || !token || !speech.trim()}
                onClick={() => void sendSpeech()}
              >
                Speak
              </button>
            </div>
          </div>

          <div className="section-card">
            <h2>Call transcript</h2>
            <div className="ivr-transcript" role="log" aria-live="polite">
              {log.length === 0 && (
                <p className="muted">Transcript appears here after you start a call.</p>
              )}
              {log.map((entry, i) => (
                <div key={i} className={`ivr-line ivr-line-${entry.kind}`}>
                  <span className="ivr-line-kind">
                    {entry.kind === "bot"
                      ? "Service"
                      : entry.kind === "prompt"
                        ? "Prompt"
                        : entry.kind === "dtmf"
                          ? "Keypad"
                          : entry.kind === "speech"
                            ? "Speech"
                            : "System"}
                  </span>
                  <span>{entry.text}</span>
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
