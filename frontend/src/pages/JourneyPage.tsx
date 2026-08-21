import { useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  encodePocVoice,
  getJourney,
  postConsent,
  sendChannelMessage,
  startJourney,
  uploadDocument,
  type JourneyResponse,
} from "../api/client";

type ChatItem = { role: "bot" | "user" | "system"; text: string };

const DOC_CODES = ["IDENTITY_PROOF", "ADDRESS_PROOF", "INCOME_PROOF"] as const;
const LANGS = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "te", label: "తెలుగు" },
];

const PERSONA_HINT =
  "Demo personas: Lakshmi 9876543210 / OTP 123456 · Ramesh 9123456780 / OTP 654321 · Anita 9988776655 / OTP 112233";

function playAudio(b64: string | null | undefined, mime?: string | null) {
  if (!b64) return;
  const audio = new Audio(`data:${mime || "audio/wav"};base64,${b64}`);
  void audio.play().catch(() => undefined);
}

export default function JourneyPage() {
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<string>("—");
  const [language, setLanguage] = useState<string>("en");
  const [prompt, setPrompt] = useState<string>("");
  const [input, setInput] = useState("");
  const [chat, setChat] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<Record<string, unknown> | null>(null);
  const [docCode, setDocCode] = useState<string>(DOC_CODES[0]);
  const [last, setLast] = useState<JourneyResponse | null>(null);
  const [transcript, setTranscript] = useState<string>("");
  const [recording, setRecording] = useState(false);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

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
    if (reply.language) setLanguage(reply.language);
    if (reply.transcript) setTranscript(reply.transcript);
    const lines = [reply.message];
    if (reply.prompt) lines.push(reply.prompt);
    if (reply.intent) lines.push(`Intent: ${reply.intent}`);
    if (reply.error) lines.push(`Error: ${reply.error}`);
    if (reply.expected_format) lines.push(`Expected: ${reply.expected_format}`);
    setChat((prev) => [...prev, { role: "bot", text: lines.filter(Boolean).join("\n") }]);
    const reviewData = reply.data?.review;
    if (reviewData && typeof reviewData === "object") {
      setReview(reviewData as Record<string, unknown>);
    }
    if (reply.state === "SUBMITTED") setReview(null);
    playAudio(reply.audio_b64, reply.audio_mime);
  }

  async function onStart() {
    setBusy(true);
    setError(null);
    setChat([]);
    setReview(null);
    setTranscript("");
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

  async function onSend(event: FormEvent) {
    event.preventDefault();
    if (!applicationId || !token || !input.trim()) return;
    const text = input.trim();
    setInput("");
    setChat((prev) => [...prev, { role: "user", text }]);
    setBusy(true);
    setError(null);
    try {
      const reply = await sendChannelMessage("web", applicationId, token, {
        text,
        language,
        modality: "text",
      });
      pushBot(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Message failed");
    } finally {
      setBusy(false);
    }
  }

  async function sendLanguage(code: string) {
    setLanguage(code);
    if (!applicationId || !token) return;
    setBusy(true);
    try {
      const reply = await sendChannelMessage("web", applicationId, token, {
        text: code,
        language: code,
      });
      setChat((prev) => [...prev, { role: "user", text: `Language: ${code}` }]);
      pushBot(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Language failed");
    } finally {
      setBusy(false);
    }
  }

  async function onVoiceSubmit(spoken: string) {
    if (!applicationId || !token || !spoken.trim()) return;
    setBusy(true);
    setError(null);
    setChat((prev) => [...prev, { role: "user", text: `🎤 ${spoken}` }]);
    try {
      const reply = await sendChannelMessage("web", applicationId, token, {
        modality: "voice",
        language,
        audio_b64: encodePocVoice(spoken),
        transcript: spoken,
      });
      pushBot(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voice failed");
    } finally {
      setBusy(false);
    }
  }

  async function toggleRecord() {
    if (recording && mediaRef.current) {
      mediaRef.current.stop();
      setRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        // POC: use typed transcript box if Web Speech unavailable;
        // fall back to input text as spoken phrase for MockSTT.
        const spoken = input.trim() || "YES";
        void onVoiceSubmit(spoken);
      };
      mediaRef.current = recorder;
      recorder.start();
      setRecording(true);
    } catch {
      // Mic denied — still allow typed "voice" via push-to-talk semantics
      const spoken = input.trim();
      if (spoken) void onVoiceSubmit(spoken);
      else setError("Allow microphone or type phrase then press Speak");
    }
  }

  async function onConsent(granted: boolean) {
    if (!applicationId || !token) return;
    setBusy(true);
    try {
      const reply = await postConsent(applicationId, token, granted);
      setChat((prev) => [
        ...prev,
        { role: "user", text: granted ? "YES (consent)" : "NO (decline)" },
      ]);
      pushBot(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Consent failed");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(file: File | null) {
    if (!file || !applicationId || !token) return;
    setBusy(true);
    setChat((prev) => [...prev, { role: "user", text: `Upload ${docCode}: ${file.name}` }]);
    try {
      const reply = await uploadDocument(applicationId, token, docCode, file);
      pushBot(reply);
      const missing = reply.data?.missing_documents;
      if (Array.isArray(missing) && missing[0]) setDocCode(String(missing[0]));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
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
            Voice + text web journey (P3). Languages: en / hi / te. Restricted data stays local.
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
          <div>
            <span className="label">Language</span>
            <strong>{language}</strong>
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
          disabled={busy || !applicationId || !token}
          onClick={() => {
            if (!applicationId || !token) return;
            void getJourney(applicationId, token).then(pushBot);
          }}
        >
          Refresh
        </button>
        <div className="lang-pills">
          {LANGS.map((l) => (
            <button
              key={l.code}
              type="button"
              className={language === l.code ? "" : "ghost"}
              disabled={busy || !applicationId}
              onClick={() => void sendLanguage(l.code)}
            >
              {l.label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {transcript && (
        <p className="meta">
          Last transcript: <em>{transcript}</em>
        </p>
      )}

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
            I agree
          </button>
          <button type="button" className="ghost" onClick={() => void onConsent(false)} disabled={busy}>
            Decline
          </button>
        </div>
      )}

      {(state === "DOCUMENT_CAPTURE" || state === "DOCUMENT_REJECTED") && (
        <div className="upload-bar">
          <label>
            Document
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
            accept=".pdf,.png,.jpg,.jpeg"
            onChange={(e) => void onUpload(e.target.files?.[0] ?? null)}
            disabled={busy}
          />
        </div>
      )}

      {review && (
        <article className="card review-card">
          <h2>Review</h2>
          <pre>{JSON.stringify(review, null, 2)}</pre>
        </article>
      )}

      <form className="composer" onSubmit={(e) => void onSend(e)}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={prompt || "Type or speak…"}
          disabled={busy || !applicationId}
        />
        <button type="submit" disabled={busy || !applicationId || !input.trim()}>
          Send
        </button>
        <button
          type="button"
          className={recording ? "" : "ghost"}
          disabled={busy || !applicationId}
          onClick={() => void toggleRecord()}
        >
          {recording ? "Stop" : "Speak"}
        </button>
      </form>
    </section>
  );
}
