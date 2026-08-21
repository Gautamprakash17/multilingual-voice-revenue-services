import { useState } from "react";
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

export default function IVRSimulatorPage() {
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState("—");
  const [prompt, setPrompt] = useState("");
  const [buffer, setBuffer] = useState("");
  const [log, setLog] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [speech, setSpeech] = useState("");
  const [error, setError] = useState<string | null>(null);

  function apply(reply: JourneyResponse) {
    setApplicationId(reply.application_id);
    if (reply.access_token) setToken(reply.access_token);
    setState(reply.state);
    setPrompt(reply.prompt || reply.message);
    setLog((l) => [...l, `BOT: ${reply.message}`, reply.prompt ? `PROMPT: ${reply.prompt}` : ""].filter(Boolean));
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

  async function sendDtmf(value: string) {
    if (!applicationId || !token) return;
    setBusy(true);
    setLog((l) => [...l, `DTMF: ${value}`]);
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
    setLog((l) => [...l, `SPEECH: ${speech}`]);
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
      <h1>IVR Simulator</h1>
      <p className="lede">
        Phone-like DTMF + simulated speech. Channel=ivr via the common MessageEnvelope.
      </p>
      {error && <div className="alert error">{error}</div>}

      <div className="journey-actions">
        <button type="button" onClick={() => void onCall()} disabled={busy}>
          Start call
        </button>
        <span className="state-pill">{state}</span>
        <strong>{applicationId ?? "—"}</strong>
      </div>

      <p className="prompt-line">{prompt || "Dial to begin"}</p>

      <div className="phone">
        <div className="phone-screen">{buffer || "—"}</div>
        <div className="keypad">
          {KEYS.map((k) => (
            <button
              key={k}
              type="button"
              className="ghost"
              disabled={busy || !token}
              onClick={() => setBuffer((b) => b + k)}
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
          <button type="button" className="ghost" onClick={() => setBuffer("")}>
            Clear
          </button>
        </div>
      </div>

      <div className="composer">
        <input
          value={speech}
          onChange={(e) => setSpeech(e.target.value)}
          placeholder="Simulated speech (e.g. en, YES, CONFIRM)"
          disabled={busy || !token}
        />
        <button type="button" disabled={busy || !token} onClick={() => void sendSpeech()}>
          Speak
        </button>
      </div>

      <div className="chat-log">
        {log.map((line, i) => (
          <div key={i} className="bubble system">
            {line}
          </div>
        ))}
      </div>
    </section>
  );
}
