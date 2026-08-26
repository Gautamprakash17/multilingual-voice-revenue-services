import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchCitizenCertificate,
  fetchLanguages,
  fetchServices,
  sendChannelMessage,
  startChannel,
  type JourneyResponse,
  type LanguageConfig,
  type ServiceConfig,
} from "../api/client";
import PhoneSimulator from "../components/PhoneSimulator";
import {
  IVR_KEYS,
  acceptsIvrKey,
  appendIvrKey,
  canSubmitIvrSpeech,
  formatIvrDateKeypadDisplay,
  formatIvrDisplay,
  isIvrDualInputStep,
  isIvrFreeFormSpeechStep,
  isIvrKeypadOpen,
  isIvrSpeakButtonEnabled,
  isIvrSpeakControlEnabled,
  ivrAudioVoicePayload,
  ivrCallPhase,
  ivrCallPhaseLabel,
  formatCallDuration,
  ivrDtmfPayload,
  ivrFieldTypeFromServices,
  ivrInputMode,
  ivrKeyLetters,
  ivrKeypadHint,
  ivrModeFromJourney,
  mergeIvrAuthStep,
  ivrSpeakButtonLabel,
  ivrSpeechListeningLabel,
  ivrVoicePayload,
  isDtmfSubmitLocked,
  languageSelectIvrPrompt,
  physicalKeyToIvrKey,
  resolveIvrAuthStep,
  shouldAcceptIvrPhysicalKey,
  shouldAutoEnterIvrListening,
  shouldAutoSubmitDtmf,
  shouldIgnoreIvrPhysicalKey,
  type IvrInputMode,
} from "../journey/ivrDtmf";
import { shouldShowPhoneSimulator } from "../journey/phoneSimulator";
import { stateLabel } from "../journey/labels";
import { ServiceAudioSession } from "../journey/serviceAudio";
import { ivrDocumentContinueCopy } from "../journey/applicationIdentity";
import { storeSessionHandoff, type WhatsAppResumeNavState } from "../journey/sessionHandoff";
import {
  IVR_MIC_DENIED_MESSAGE,
  IVR_MIC_SILENCE_MESSAGE,
  captureMicUtterance,
  isBrowserMicSupported,
  isMicPermissionDeniedError,
  isUsableRecordingBlob,
  recordingBlobToWavBase64,
  type MicCaptureHandle,
} from "../journey/voiceRecording";

type LogEntry = { kind: "bot" | "prompt" | "dtmf" | "speech" | "system"; text: string };

export default function IVRSimulatorPage() {
  const navigate = useNavigate();
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [lastApplicationId, setLastApplicationId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState("—");
  const [authStep, setAuthStep] = useState("");
  const [otpIssued, setOtpIssued] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [buffer, setBuffer] = useState("");
  const [log, setLog] = useState<LogEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [speech, setSpeech] = useState("");
  const [listening, setListening] = useState(false);
  const [micActive, setMicActive] = useState(false);
  const [micDenied, setMicDenied] = useState(false);
  const [callSeconds, setCallSeconds] = useState(0);
  const [pressedKey, setPressedKey] = useState<string | null>(null);
  const [lastHeard, setLastHeard] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [languages, setLanguages] = useState<LanguageConfig[]>([]);
  const [services, setServices] = useState<ServiceConfig[]>([]);
  const [nextField, setNextField] = useState<string | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const speechInputRef = useRef<HTMLInputElement>(null);
  const phoneKeypadRef = useRef<HTMLDivElement>(null);
  const sendingRef = useRef(false);
  const bufferRef = useRef("");
  const audioRef = useRef(new ServiceAudioSession({ volume: 0.45 }));
  const onKeyRef = useRef<(key: string) => void>(() => undefined);
  const keypadModeRef = useRef(false);
  const speechModeRef = useRef(false);
  const inCallRef = useRef(false);
  const busyRef = useRef(false);
  const stateRef = useRef<string>("—");
  const authStepRef = useRef("");
  const nextFieldRef = useRef<string | null>(null);
  const applicationIdRef = useRef<string | null>(null);
  const tokenRef = useRef<string | null>(null);
  const speechStepKeyRef = useRef("");
  const speechRef = useRef("");
  const pressTimerRef = useRef(0);
  const micHandleRef = useRef<MicCaptureHandle | null>(null);
  const micGenRef = useRef(0);

  const inCall = Boolean(token && applicationId);
  const resolvedAuthStep = resolveIvrAuthStep(state === "—" ? null : state, authStep);
  const captureHint = {
    nextField,
    fieldType: ivrFieldTypeFromServices(nextField, services),
  };
  const mode: IvrInputMode = ivrInputMode(
    state === "—" ? null : state,
    resolvedAuthStep,
    captureHint,
  );
  const speechMode = isIvrFreeFormSpeechStep(mode);
  const keypadMode = isIvrKeypadOpen(mode);
  const dualInput = isIvrDualInputStep(mode);
  const phase = ivrCallPhase({ inCall, busy, state: state === "—" ? null : state, mode });
  const keypadHint = useMemo(
    () =>
      ivrKeypadHint(mode, {
        languages: languages.map((l) => ({
          code: l.code,
          display_name: l.display_name,
        })),
        services: services.map((s) => ({
          code: s.code,
          display_name: s.display_name,
        })),
      }),
    [mode, languages, services],
  );

  inCallRef.current = inCall;
  busyRef.current = busy;
  applicationIdRef.current = applicationId;
  tokenRef.current = token;
  if (!isDtmfSubmitLocked(sendingRef.current, busyRef.current)) {
    keypadModeRef.current = keypadMode;
    speechModeRef.current = speechMode;
    stateRef.current = state === "—" ? "—" : state;
    authStepRef.current = resolvedAuthStep;
    nextFieldRef.current = nextField;
  }

  useEffect(() => {
    if (!inCall) {
      setCallSeconds(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      setCallSeconds(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [inCall, applicationId]);

  useEffect(() => {
    void fetchLanguages()
      .then((catalog) => setLanguages(catalog.languages))
      .catch(() => setLanguages([]));
    void fetchServices()
      .then((catalog) => setServices(catalog.services))
      .catch(() => setServices([]));
    const audio = audioRef.current;
    return () => {
      stopMicCapture();
      audio.clear();
    };
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [log]);

  // Free-form speech → barge-in TTS and start real microphone capture.
  useEffect(() => {
    if (!inCall || !speechMode) {
      stopMicCapture();
      setListening(false);
      setMicActive(false);
      speechStepKeyRef.current = "";
      return;
    }
    // Date keypad digits in progress — don't steal them with auto-listen.
    if (dualInput && buffer.length > 0) {
      stopMicCapture();
      setListening(false);
      setMicActive(false);
      return;
    }
    if (!shouldAutoEnterIvrListening({ inCall, speechMode, busy })) {
      stopMicCapture();
      setListening(false);
      setMicActive(false);
      return;
    }
    const stepKey = `${state}:${resolvedAuthStep}:${nextField ?? ""}`;
    if (speechStepKeyRef.current !== stepKey) {
      speechStepKeyRef.current = stepKey;
      speechRef.current = "";
      setSpeech("");
      setLastHeard(null);
    }
    audioRef.current.interruptForRecording();
    setListening(true);
    void beginMicCapture();
    return () => {
      // New effect run / unmount — abandon in-flight capture for this generation.
      stopMicCapture();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inCall, speechMode, resolvedAuthStep, state, busy, dualInput, buffer, nextField]);

  // DTMF steps → focus the phone keypad so laptop keys hit the same onKey path.
  useEffect(() => {
    if (!inCall || !keypadMode || busy) return;
    const id = window.setTimeout(() => {
      phoneKeypadRef.current?.focus({ preventScroll: true });
    }, 0);
    return () => window.clearTimeout(id);
  }, [inCall, keypadMode, busy, state, resolvedAuthStep, nextField]);

  useEffect(() => {
    function onPhysicalKey(event: KeyboardEvent) {
      if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
      if (shouldIgnoreIvrPhysicalKey(event.target)) return;
      if (
        phoneKeypadRef.current &&
        event.target instanceof Node &&
        phoneKeypadRef.current.contains(event.target)
      ) {
        return;
      }
      if (
        !shouldAcceptIvrPhysicalKey({
          inCall: inCallRef.current,
          keypadMode: keypadModeRef.current,
          speechMode: speechModeRef.current,
          busy: isDtmfSubmitLocked(sendingRef.current, busyRef.current),
        })
      ) {
        return;
      }
      const mapped = physicalKeyToIvrKey(event.key);
      if (!mapped) return;
      event.preventDefault();
      onKeyRef.current(mapped);
    }
    window.addEventListener("keydown", onPhysicalKey, true);
    return () => window.removeEventListener("keydown", onPhysicalKey, true);
  }, []);

  function setDtmfBuffer(next: string) {
    bufferRef.current = next;
    setBuffer(next);
  }

  function stopMicCapture() {
    micGenRef.current += 1;
    const handle = micHandleRef.current;
    micHandleRef.current = null;
    handle?.stop();
    setMicActive(false);
  }

  async function beginMicCapture() {
    if (sendingRef.current || busyRef.current) return;
    if (!isBrowserMicSupported()) {
      setMicDenied(true);
      setMicActive(false);
      setError(IVR_MIC_DENIED_MESSAGE);
      return;
    }
    stopMicCapture();
    const gen = micGenRef.current;
    try {
      audioRef.current.interruptForRecording();
      const { handle, done } = await captureMicUtterance();
      if (gen !== micGenRef.current) {
        handle.stop();
        return;
      }
      micHandleRef.current = handle;
      setMicDenied(false);
      setMicActive(true);
      setListening(true);
      setError(null);
      const result = await done;
      if (gen !== micGenRef.current) return;
      micHandleRef.current = null;
      setMicActive(false);
      await processMicResult(result.blob, result.heardSpeech);
    } catch (err) {
      if (gen !== micGenRef.current) return;
      micHandleRef.current = null;
      setMicActive(false);
      if (isMicPermissionDeniedError(err)) {
        setMicDenied(true);
        setError(IVR_MIC_DENIED_MESSAGE);
        setListening(true);
        return;
      }
      setError(err instanceof Error ? err.message : "Microphone failed");
      setListening(true);
    }
  }

  async function processMicResult(blob: Blob, heardSpeech: boolean) {
    if (!isUsableRecordingBlob(blob, heardSpeech)) {
      setError(IVR_MIC_SILENCE_MESSAGE);
      setListening(true);
      // Auto-retry listening after a short pause (same call / auth step).
      window.setTimeout(() => {
        if (
          shouldAutoEnterIvrListening({
            inCall: inCallRef.current,
            speechMode: speechModeRef.current,
            busy: busyRef.current,
          }) &&
          !sendingRef.current
        ) {
          void beginMicCapture();
        }
      }, 600);
      return;
    }
    try {
      const audio_b64 = await recordingBlobToWavBase64(blob);
      await sendVoicePayload(ivrAudioVoicePayload(audio_b64), "Voice (microphone)");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not process recording");
      setListening(true);
    }
  }

  function apply(reply: JourneyResponse) {
    setApplicationId(reply.application_id);
    applicationIdRef.current = reply.application_id;
    setLastApplicationId(reply.application_id);
    if (reply.access_token) {
      setToken(reply.access_token);
      tokenRef.current = reply.access_token;
      storeSessionHandoff(reply.application_id, reply.access_token);
    }
    setState(reply.state);
    stateRef.current = reply.state;
    const incoming =
      typeof reply.data?.auth_step === "string" ? reply.data.auth_step : "";
    const step = mergeIvrAuthStep(reply.state, incoming, authStepRef.current);
    setAuthStep(step);
    authStepRef.current = step;
    const nxt =
      typeof reply.data?.next_field === "string" && reply.data.next_field
        ? reply.data.next_field
        : typeof reply.data?.field === "string" && reply.data.field
          ? reply.data.field
          : null;
    setNextField(nxt);
    nextFieldRef.current = nxt;
    const nextMode = ivrModeFromJourney(reply.state, step, {
      nextField: nxt,
      fieldType: ivrFieldTypeFromServices(nxt, services),
    });
    speechModeRef.current = isIvrFreeFormSpeechStep(nextMode);
    keypadModeRef.current = isIvrKeypadOpen(nextMode);
    setOtpIssued(reply.data?.otp_issued === true);
    const nextPrompt = reply.prompt || reply.message;
    setPrompt(nextPrompt);
    if (reply.transcript) {
      setLastHeard(reply.transcript);
    }
    setLog((l) => {
      const next: LogEntry[] = [...l, { kind: "bot", text: reply.message }];
      if (reply.prompt && reply.prompt !== reply.message) {
        next.push({ kind: "prompt", text: reply.prompt });
      }
      return next;
    });
    if (reply.error === "stt_unrecognized") {
      setError(reply.message || IVR_MIC_SILENCE_MESSAGE);
    }
    if (reply.audio_b64) {
      audioRef.current.play(reply.audio_b64, reply.audio_mime);
    }
  }

  async function onCall() {
    stopMicCapture();
    audioRef.current.clear();
    setBusy(true);
    busyRef.current = true;
    setError(null);
    setLog([]);
    setDtmfBuffer("");
    setAuthStep("");
    authStepRef.current = "";
    setNextField(null);
    nextFieldRef.current = null;
    stateRef.current = "—";
    setOtpIssued(false);
    setSpeech("");
    speechRef.current = "";
    setListening(false);
    setMicActive(false);
    setMicDenied(false);
    setLastHeard(null);
    try {
      const reply = await startChannel("ivr");
      apply(reply);
      if (reply.state === "LANGUAGE_SELECT" && languages.length > 0) {
        setPrompt(
          languageSelectIvrPrompt(
            languages.map((l) => ({ code: l.code, display_name: l.display_name })),
          ),
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Call failed");
    } finally {
      sendingRef.current = false;
      busyRef.current = false;
      setBusy(false);
    }
  }

  function continueOnWhatsApp(appId: string) {
    const sessionToken = tokenRef.current;
    if (sessionToken) {
      storeSessionHandoff(appId, sessionToken);
    }
    navigate("/whatsapp", {
      state: {
        resumeFromWeb: true,
        applicationId: appId,
      } satisfies WhatsAppResumeNavState,
    });
  }

  function onEndCall() {
    stopMicCapture();
    audioRef.current.clear();
    const endedId = applicationIdRef.current;
    if (endedId) setLastApplicationId(endedId);
    setApplicationId(null);
    applicationIdRef.current = null;
    setToken(null);
    tokenRef.current = null;
    setState("—");
    stateRef.current = "—";
    setAuthStep("");
    authStepRef.current = "";
    setNextField(null);
    nextFieldRef.current = null;
    setOtpIssued(false);
    setPrompt("");
    setDtmfBuffer("");
    setSpeech("");
    speechRef.current = "";
    setListening(false);
    setMicActive(false);
    setMicDenied(false);
    setLastHeard(null);
    sendingRef.current = false;
    busyRef.current = false;
    setLog((l) => [...l, { kind: "system", text: "Call ended" }]);
  }

  async function sendDtmf(value: string) {
    const appId = applicationIdRef.current;
    const tok = tokenRef.current;
    if (!appId || !tok || !value || sendingRef.current) return;
    stopMicCapture();
    sendingRef.current = true;
    busyRef.current = true;
    setBusy(true);
    setDtmfBuffer("");
    setLog((l) => [...l, { kind: "dtmf", text: value }]);
    try {
      apply(await sendChannelMessage("ivr", appId, tok, ivrDtmfPayload(value)));
      setDtmfBuffer("");
      setError(null);
    } catch (err) {
      setDtmfBuffer("");
      setError(err instanceof Error ? err.message : "DTMF failed");
    } finally {
      sendingRef.current = false;
      busyRef.current = false;
      setBusy(false);
    }
  }

  function journeyCaptureHint() {
    const name = nextFieldRef.current;
    return {
      nextField: name,
      fieldType: ivrFieldTypeFromServices(name, services),
    };
  }

  function flashKey(key: string) {
    setPressedKey(key);
    window.clearTimeout(pressTimerRef.current);
    pressTimerRef.current = window.setTimeout(() => setPressedKey(null), 160);
  }

  function onKey(key: string) {
    if (!inCallRef.current || isDtmfSubmitLocked(sendingRef.current, busyRef.current)) {
      return;
    }
    audioRef.current.interruptForRecording();
    const modeNow = ivrModeFromJourney(
      stateRef.current,
      authStepRef.current,
      journeyCaptureHint(),
    );
    const keypadNow = isIvrKeypadOpen(modeNow);
    if (!keypadNow) return;

    if (isIvrDualInputStep(modeNow)) {
      stopMicCapture();
      setListening(false);
    }

    if (modeNow === "collect" && key === "#") {
      if (bufferRef.current) {
        flashKey(key);
        void sendDtmf(bufferRef.current);
      }
      return;
    }
    const next = appendIvrKey(bufferRef.current, key, modeNow);
    if (next === bufferRef.current) return;
    flashKey(key);
    setDtmfBuffer(next);
    if (shouldAutoSubmitDtmf(modeNow, next, key)) {
      void sendDtmf(next);
    }
  }
  onKeyRef.current = onKey;

  async function sendVoicePayload(
    payload: { modality: "voice"; transcript?: string; audio_b64?: string },
    logLabel: string,
  ) {
    const appId = applicationIdRef.current;
    const tok = tokenRef.current;
    if (!appId || !tok || sendingRef.current) return;
    const modeNow = ivrModeFromJourney(
      stateRef.current,
      authStepRef.current,
      journeyCaptureHint(),
    );
    if (!isIvrFreeFormSpeechStep(modeNow)) return;

    stopMicCapture();
    audioRef.current.interruptForRecording();
    setListening(false);
    sendingRef.current = true;
    busyRef.current = true;
    setBusy(true);
    setLog((l) => [...l, { kind: "speech", text: logLabel }]);
    try {
      const reply = await sendChannelMessage("ivr", appId, tok, payload);
      apply(reply);
      speechRef.current = "";
      setSpeech("");
      setDtmfBuffer("");
      if (reply.error !== "stt_unrecognized") {
        setError(null);
      }
      if (reply.transcript) {
        setLog((l) => {
          const next = [...l];
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].kind === "speech" && next[i].text === logLabel) {
              next[i] = { kind: "speech", text: reply.transcript as string };
              break;
            }
          }
          return next;
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Speech failed");
    } finally {
      sendingRef.current = false;
      busyRef.current = false;
      setBusy(false);
    }
  }

  /** Developer fallback — typed transcript only (no empty submit). */
  async function sendSpeechFallback() {
    const transcript = speechRef.current.trim();
    if (!canSubmitIvrSpeech(transcript)) {
      setListening(true);
      return;
    }
    await sendVoicePayload(ivrVoicePayload(transcript), transcript);
  }

  function renderSpeechPrimary() {
    return (
      <div className={`ivr-speech-primary${listening || micActive ? " ivr-speech-listening" : ""}`}>
        <p className="ivr-speech-primary-label" role="status" aria-live="polite">
          {ivrSpeechListeningLabel(listening, busy, {
            micActive,
            micDenied,
            keypadAvailable: dualInput,
          })}
        </p>
        {lastHeard && !busy && !micActive && (
          <p className="ivr-heard muted" aria-live="polite">
            I heard: {lastHeard}
          </p>
        )}
        <div className="ivr-mic-row">
          <span className={`ivr-mic-dot${micActive ? " active" : ""}`} aria-hidden="true" />
          <p className="ivr-mic-caption">
            {micActive
              ? "Use microphone — speak now"
              : busy
                ? "Processing speech…"
                : micDenied
                  ? "Microphone blocked — use developer fallback below"
                  : "Use microphone — waiting to listen"}
          </p>
          {!micActive && !busy && speechMode && (
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setError(null);
                void beginMicCapture();
              }}
            >
              Listen again
            </button>
          )}
        </div>

        <details className="ivr-dev-fallback">
          <summary>Developer fallback</summary>
          <p className="muted">
            Type a transcript only when the microphone is unavailable. Normal IVR use should speak
            into the mic.
          </p>
          <div className="composer">
            <label htmlFor="ivr-speech-fallback" className="visually-hidden">
              Developer fallback transcript
            </label>
            <input
              id="ivr-speech-fallback"
              ref={speechInputRef}
              value={speech}
              onChange={(e) => {
                speechRef.current = e.target.value;
                setSpeech(e.target.value);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  if (canSubmitIvrSpeech(speechRef.current)) {
                    void sendSpeechFallback();
                  }
                }
              }}
              placeholder="e.g. Gautam Prakash"
              disabled={
                !isIvrSpeakControlEnabled({
                  speechMode,
                  hasToken: Boolean(token),
                  busy,
                })
              }
              aria-label="Developer fallback transcript"
            />
            <button
              type="button"
              disabled={
                !isIvrSpeakButtonEnabled({
                  speechMode,
                  hasToken: Boolean(token),
                  busy,
                  transcript: speech,
                })
              }
              onClick={() => void sendSpeechFallback()}
            >
              {ivrSpeakButtonLabel({ busy, speechMode })}
            </button>
          </div>
        </details>
      </div>
    );
  }

  function renderKeypad() {
    const screenValue =
      mode === "confirm"
        ? buffer || "1 / 2"
        : mode === "collect"
          ? formatIvrDateKeypadDisplay(buffer)
          : formatIvrDisplay(buffer);
    return (
      <div
        className={`phone${keypadMode && inCall ? " phone-keypad-active" : ""}`}
        aria-label="Telephone keypad"
        ref={phoneKeypadRef}
        tabIndex={0}
        onKeyDown={(e) => {
          if (shouldIgnoreIvrPhysicalKey(e.target)) return;
          const mapped = physicalKeyToIvrKey(e.key);
          if (!mapped) return;
          e.preventDefault();
          e.stopPropagation();
          onKey(mapped);
        }}
      >
        <div className="phone-screen" aria-live="polite">
          {screenValue}
        </div>
        <div className={`keypad${mode === "confirm" ? " keypad-confirm" : ""}`}>
          {IVR_KEYS.map((k) => {
            const allowed = !token || !keypadMode ? false : acceptsIvrKey(mode, k);
            const letters = ivrKeyLetters(k);
            return (
              <button
                key={k}
                type="button"
                className={[
                  mode === "confirm" && (k === "1" || k === "2") ? "ivr-key-emphasis" : "",
                  pressedKey === k ? "pressed" : "",
                ]
                  .filter(Boolean)
                  .join(" ") || undefined}
                disabled={!token || !keypadMode || !allowed}
                onClick={() => onKey(k)}
                aria-label={`Key ${k}`}
                aria-pressed={pressedKey === k}
              >
                <span>{k}</span>
                {letters ? <span className="key-letters">{letters}</span> : null}
              </button>
            );
          })}
        </div>
        <div className="journey-actions">
          <button
            type="button"
            className="ghost"
            onClick={() => {
              audioRef.current.interruptForRecording();
              setDtmfBuffer("");
            }}
            disabled={!buffer}
          >
            Clear
          </button>
        </div>
      </div>
    );
  }

  return (
    <section className="panel ivr-sim ivr-sim-focus">
      <span className="sim-banner" role="status">
        Demonstration simulator — not a live phone line
      </span>
      <header className="sim-page-head">
        <div>
          <p className="eyebrow">Demonstration</p>
          <h1>IVR</h1>
        </div>
        <p className="sim-page-lede muted">
          Keypad for menus, codes, and date of birth · microphone for spoken answers.
        </p>
      </header>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}

      {applicationId && token && (
        <PhoneSimulator
          applicationId={applicationId}
          token={token}
          otpActive={shouldShowPhoneSimulator({ state, authStep: resolvedAuthStep, otpIssued })}
          onViewCertificate={() => {
            void fetchCitizenCertificate(applicationId, token, { download: false })
              .then((blob) => {
                const url = URL.createObjectURL(blob);
                window.open(url, "_blank", "noopener,noreferrer");
                window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
              })
              .catch((err: unknown) => {
                setError(
                  err instanceof Error ? err.message : "Certificate is not available yet.",
                );
              });
          }}
        />
      )}

      <div className="ivr-layout-connected">
      <div className={`ivr-phone-shell${dualInput ? " ivr-dob-dual" : ""}`}>
        {inCall && (
          <div className="ivr-call-banner" role="status" aria-live="polite">
            <span className="ivr-call-live">Call connected</span>
            <span className="ivr-call-timer">{formatCallDuration(callSeconds)}</span>
          </div>
        )}
        <div className="ivr-phone-top">
          <div className="ivr-caller">
            <strong>Revenue Services</strong>
            <p className="call-status-label">
              {inCall ? `In call · ${formatCallDuration(callSeconds)}` : "Idle"}
            </p>
          </div>
          {inCall ? (
            <p
              className={`ivr-modality${speechMode ? " ivr-modality-speech" : keypadMode ? " ivr-modality-keypad" : ""}`}
              aria-live="polite"
            >
              {speechMode && keypadMode
                ? listening || micActive
                  ? "Listening… keypad also ready"
                  : busy
                    ? "Processing…"
                    : "Speak or use keypad"
                : speechMode
                ? listening || micActive
                  ? "Listening…"
                  : busy
                    ? "Processing…"
                    : "Speak your answer"
                : keypadMode
                  ? "Keypad active"
                  : ivrCallPhaseLabel(phase)}
            </p>
          ) : null}
          <p className="meta">
            {applicationId ?? lastApplicationId ?? "No call yet"}
            {state !== "—" ? ` · ${stateLabel(state)}` : ""}
          </p>
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
            {applicationId && token && (
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() => continueOnWhatsApp(applicationId)}
              >
                Continue on WhatsApp
              </button>
            )}
          </div>
        </div>

        <p className="prompt-line ivr-prompt" aria-live="polite">
          {prompt || "Press Start call to begin"}
        </p>
        {inCall && <p className="ivr-key-hint">{keypadHint}</p>}

        {state === "DOCUMENT_CAPTURE" && applicationId && (
          <div className="ivr-doc-continue" role="status">
            <p>{ivrDocumentContinueCopy(applicationId)}</p>
            <button
              type="button"
              className="ghost"
              onClick={() => continueOnWhatsApp(applicationId)}
            >
              Continue on WhatsApp
            </button>
          </div>
        )}
        {!inCall && lastApplicationId && state === "—" && (
          <div className="ivr-doc-continue" role="status">
            <p>
              Last Application ID <strong>{lastApplicationId}</strong>. Continue on WhatsApp in
              this browser to resume the same application.
            </p>
            <button
              type="button"
              className="ghost"
              onClick={() => continueOnWhatsApp(lastApplicationId)}
            >
              Continue on WhatsApp
            </button>
          </div>
        )}

        {inCall && speechMode ? renderSpeechPrimary() : null}
        {!inCall || keypadMode ? renderKeypad() : null}
      </div>

      <div className="ivr-side-stack">
        <div className="section-card ivr-transcript-card">
          <h2>Call transcript</h2>
          <div className="ivr-transcript" role="log" aria-live="polite">
            {log.length === 0 && (
              <div className="conversation-empty ivr-transcript-empty" role="status">
                <p className="conversation-empty-title">No transcript yet</p>
                <p className="muted">Start a call to see the conversation here.</p>
              </div>
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
