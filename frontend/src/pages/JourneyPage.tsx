import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  encodePocVoice,
  fetchLanguages,
  fetchServices,
  getJourney,
  postConsent,
  sendChannelMessage,
  startChannel,
  uploadDocument,
  type JourneyResponse,
  type LanguageConfig,
  type ServiceConfig,
} from "../api/client";
import { INTERNAL_UI_ERRORS, JOURNEY_COMMANDS, acceptsCitizenComposer, showsFieldConfirmationActions, showsPaymentActions } from "../journey/actions";
import {
  citizenFieldCaption,
  draftFromCaptured,
  draftValueForBackend,
  emptyDraft,
  fieldInputMode,
  fieldInputType,
  findFirstMissingRequired,
  missingRequiredMessage,
  type FormDraft,
} from "../journey/form";
import { citizenVisibleText } from "../journey/chatText";
import { storeSessionHandoff, type WhatsAppResumeNavState } from "../journey/sessionHandoff";
import {
  applyForServiceLabel,
  documentLabel,
  fieldLabel,
  formatFee,
  serviceDisplayName,
  stateLabel,
  verificationStatusLabel,
  VERIFICATION_POC_NOTE,
} from "../journey/labels";
import { ServiceAudioSession } from "../journey/serviceAudio";

type ChatItem = { role: "bot" | "user" | "system"; text: string };

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result;
      if (typeof result !== "string") {
        reject(new Error("Could not read audio"));
        return;
      }
      const comma = result.indexOf(",");
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(new Error("Could not read audio"));
    reader.readAsDataURL(blob);
  });
}

const WHISPER_SAMPLE_RATE = 16000;

function writeAscii(view: DataView, offset: number, text: string) {
  for (let i = 0; i < text.length; i++) {
    view.setUint8(offset + i, text.charCodeAt(i));
  }
}

function encodeWavPcm16(samples: Float32Array, sampleRate: number): Blob {
  const bytesPerSample = 2;
  const blockAlign = bytesPerSample;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, dataSize, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

/** Decode browser MediaRecorder output and resample to 16 kHz mono WAV for local STT. */
async function recordingBlobToWavBase64(blob: Blob): Promise<string> {
  const arrayBuffer = await blob.arrayBuffer();
  const decodeCtx = new AudioContext();
  try {
    const decoded = await decodeCtx.decodeAudioData(arrayBuffer.slice(0));
    const frames = Math.max(1, Math.ceil(decoded.duration * WHISPER_SAMPLE_RATE));
    const offline = new OfflineAudioContext(1, frames, WHISPER_SAMPLE_RATE);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start(0);
    const rendered = await offline.startRendering();
    const wavBlob = encodeWavPcm16(rendered.getChannelData(0), WHISPER_SAMPLE_RATE);
    return blobToBase64(wavBlob);
  } finally {
    void decodeCtx.close();
  }
}

type ServiceAudioState = "idle" | "playing" | "blocked";

type VoicePhase = "idle" | "listening" | "processing";

function useLanguageCatalog() {
  const [languages, setLanguages] = useState<LanguageConfig[]>([]);
  const [defaultLanguage, setDefaultLanguage] = useState("en");

  useEffect(() => {
    void fetchLanguages().then((catalog) => {
      setLanguages(catalog.languages);
      setDefaultLanguage(catalog.default);
    });
  }, []);

  const supportedCodes = useMemo(
    () => new Set(languages.map((lang) => lang.code)),
    [languages],
  );

  function normalizeLang(code: string | null | undefined): string {
    const c = (code || defaultLanguage).trim().toLowerCase();
    return supportedCodes.has(c) ? c : defaultLanguage;
  }

  function languageLabel(code: string): string {
    const match = languages.find((lang) => lang.code === code);
    return match?.native_name || match?.display_name || code;
  }

  return { languages, defaultLanguage, normalizeLang, languageLabel, supportedCodes };
}

function useServiceCatalog() {
  const [services, setServices] = useState<ServiceConfig[]>([]);

  useEffect(() => {
    void fetchServices().then((catalog) => setServices(catalog.services));
  }, []);

  return services;
}

type ReviewDocument = {
  code: string;
  filename?: string;
  verification_status?: string;
};

type ReviewPayload = {
  fields?: Record<string, unknown>;
  documents?: ReviewDocument[];
  service?: string;
  application_id?: string;
};

export default function JourneyPage() {
  const navigate = useNavigate();
  const { languages, defaultLanguage, normalizeLang, languageLabel } = useLanguageCatalog();
  const services = useServiceCatalog();
  const [applicationId, setApplicationId] = useState<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<string>("—");
  const [language, setLanguage] = useState<string>(defaultLanguage);
  const [input, setInput] = useState("");
  const [chat, setChat] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [review, setReview] = useState<ReviewPayload | null>(null);
  const [docCode, setDocCode] = useState<string>("");
  const [selectedDocTypes, setSelectedDocTypes] = useState<Record<string, string>>({});
  const [pendingFiles, setPendingFiles] = useState<Record<string, File | null>>({});
  const [paymentProcessing, setPaymentProcessing] = useState(false);
  const [mockPayOpen, setMockPayOpen] = useState(false);
  const [last, setLast] = useState<JourneyResponse | null>(null);
  const [transcript, setTranscript] = useState<string>("");
  const [voicePhase, setVoicePhase] = useState<VoicePhase>("idle");
  const [voiceNote, setVoiceNote] = useState<string | null>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const typedAtRecordStart = useRef<string>("");
  const serviceAudioSessionRef = useRef<ServiceAudioSession | null>(null);
  if (!serviceAudioSessionRef.current) {
    serviceAudioSessionRef.current = new ServiceAudioSession();
  }
  const [serviceAudio, setServiceAudio] = useState<{ b64: string; mime: string } | null>(
    null,
  );
  const [serviceAudioState, setServiceAudioState] = useState<ServiceAudioState>("idle");
  const [formDraft, setFormDraft] = useState<FormDraft>({});
  const [editMode, setEditMode] = useState(false);
  const [selectedServiceCode, setSelectedServiceCode] = useState<string | null>(null);
  const [invalidFieldName, setInvalidFieldName] = useState<string | null>(null);
  /* Backend-expected form field — survives validation replies that omit next_field. */
  const [formCursorField, setFormCursorField] = useState<string | null>(null);
  const [capturedFormData, setCapturedFormData] = useState<Record<string, unknown>>({});
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const isListening = voicePhase === "listening";
  const isVoiceProcessing = voicePhase === "processing";
  const isServicePlaying = serviceAudioState === "playing";

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat, state]);

  useEffect(() => {
    const session = serviceAudioSessionRef.current;
    if (!session) return;
    session.setUiStateListener((next) => {
      setServiceAudioState(next);
      const payload = session.getLastPayload();
      setServiceAudio(payload);
    });
    return () => {
      session.setUiStateListener(undefined);
      session.clear();
    };
  }, []);

  const activeService = useMemo(() => {
    const code =
      selectedServiceCode ||
      (typeof last?.data?.service_code === "string" ? last.data.service_code : null) ||
      review?.service ||
      services[0]?.code ||
      null;
    return services.find((item) => item.code === code) || services[0] || null;
  }, [services, selectedServiceCode, last, review]);

  const serviceFields = useMemo(() => activeService?.fields || [], [activeService]);
  const serviceDocuments = useMemo(
    () => activeService?.documents || [],
    [activeService],
  );

  const nextField = useMemo(() => {
    const fromReply = last?.data?.next_field;
    if (typeof fromReply === "string") return fromReply;
    if (last?.error === "validation_failed") {
      const failed = last?.data?.field;
      if (typeof failed === "string") return failed;
    }
    if (formCursorField) return formCursorField;
    for (const field of serviceFields) {
      if (field.required && !(field.name in capturedFormData)) {
        return field.name;
      }
    }
    return serviceFields[0]?.name || null;
  }, [last, formCursorField, serviceFields, capturedFormData]);

  const feeInfo = useMemo(() => {
    const fee = last?.data?.fee;
    if (!fee || typeof fee !== "object") {
      if (activeService?.fee) {
        return {
          amountPaise: activeService.fee.amount_paise,
          currency: activeService.fee.currency,
          display: formatFee(activeService.fee.amount_paise, activeService.fee.currency),
        };
      }
      return null;
    }
    const amount = (fee as { amount_paise?: number }).amount_paise;
    const currency = (fee as { currency?: string }).currency || "INR";
    if (typeof amount !== "number") return null;
    return { amountPaise: amount, currency, display: formatFee(amount, currency) };
  }, [last, activeService]);

  const todayIso = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const missingDocs = useMemo(() => {
    const missing = last?.data?.missing_documents;
    return Array.isArray(missing) ? (missing as string[]) : [];
  }, [last]);

  const showComposer = acceptsCitizenComposer(state);
  const showPaymentActions = showsPaymentActions(state);

  useEffect(() => {
    if (state !== "PAYMENT") {
      setMockPayOpen(false);
      setPaymentProcessing(false);
    }
  }, [state]);

  useEffect(() => {
    if (!docCode && serviceDocuments[0]?.code) {
      setDocCode(serviceDocuments[0].code);
    }
  }, [docCode, serviceDocuments]);

  useEffect(() => {
    if (!showComposer && isListening && mediaRef.current) {
      try {
        mediaRef.current.stop();
      } catch {
        /* ignore */
      }
      mediaRef.current = null;
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
      chunksRef.current = [];
      setVoicePhase("idle");
      setVoiceNote(null);
    }
  }, [showComposer, isListening]);

  function stopServiceAudio() {
    serviceAudioSessionRef.current?.stopPlayback();
    setServiceAudioState("idle");
  }

  function playServiceAudio(b64: string, mime?: string | null) {
    if (!b64) return;
    const session = serviceAudioSessionRef.current;
    if (!session) return;
    session.play(b64, mime);
    setServiceAudio(session.getLastPayload());
    setServiceAudioState(session.getUiState());
  }

  function replayServiceAudio() {
    const session = serviceAudioSessionRef.current;
    if (!session?.getLastPayload()) return;
    session.replay();
    setServiceAudio(session.getLastPayload());
    setServiceAudioState(session.getUiState());
  }

  function pushBot(reply: JourneyResponse, opts?: { playAudio?: boolean }) {
    setLast(reply);
    setState(reply.state);
    setApplicationId(reply.application_id);
    if (reply.access_token) {
      setToken(reply.access_token);
      storeSessionHandoff(reply.application_id, reply.access_token);
    } else if (token) {
      storeSessionHandoff(reply.application_id, token);
    }
    if (reply.language) setLanguage(normalizeLang(reply.language));
    if (reply.transcript) setTranscript(reply.transcript);
    if (typeof reply.data?.service_code === "string") {
      setSelectedServiceCode(reply.data.service_code);
    }
    const visible = citizenVisibleText(reply.message, reply.prompt);
    const lines = [visible];
    if (
      reply.error &&
      !INTERNAL_UI_ERRORS.has(reply.error) &&
      reply.message &&
      !visible.includes(reply.message.trim())
    ) {
      lines.push(reply.message);
    } else if (
      reply.error &&
      !INTERNAL_UI_ERRORS.has(reply.error) &&
      !reply.message
    ) {
      lines.push("Something went wrong. Please try again.");
    }
    if (
      reply.expected_format &&
      !INTERNAL_UI_ERRORS.has(reply.error ?? "") &&
      reply.error === "validation_failed"
    ) {
      lines.push("Please check the format and try again.");
    }
    const botText = lines.filter(Boolean).join("\n");
    if (botText) {
      setChat((prev) => [...prev, { role: "bot", text: botText }]);
    }
    const reviewData = reply.data?.review;
    if (reviewData && typeof reviewData === "object") {
      const payload = reviewData as ReviewPayload;
      setReview(payload);
      if (payload.service) setSelectedServiceCode(payload.service);
      const fieldsForDraft =
        services.find((item) => item.code === (payload.service || selectedServiceCode))?.fields ||
        serviceFields;
      if (payload.fields && fieldsForDraft.length) {
        setFormDraft(draftFromCaptured(fieldsForDraft, payload.fields));
      }
    }
    const formData = reply.data?.form_data;
    if (formData && typeof formData === "object") {
      setCapturedFormData(formData as Record<string, unknown>);
      const code =
        (typeof reply.data?.service_code === "string" && reply.data.service_code) ||
        selectedServiceCode ||
        services[0]?.code;
      const fieldsForDraft =
        services.find((item) => item.code === code)?.fields || serviceFields;
      if (fieldsForDraft.length) {
        setFormDraft((prev) => ({
          ...prev,
          ...draftFromCaptured(fieldsForDraft, formData as Record<string, unknown>),
        }));
      }
    }
    if (typeof reply.data?.next_field === "string") {
      setFormCursorField(reply.data.next_field);
    } else if (
      reply.error === "validation_failed" &&
      typeof reply.data?.field === "string"
    ) {
      setFormCursorField(reply.data.field);
    } else if (
      reply.state === "FIELD_CONFIRMATION" &&
      typeof reply.data?.field === "string"
    ) {
      setFormCursorField(reply.data.field);
    }
    if (reply.state && reply.state !== "FORM_CAPTURE" && reply.state !== "CORRECTION" && reply.state !== "FIELD_CONFIRMATION") {
      if (reply.state !== "REVIEW_CONFIRM") {
        setFormCursorField(null);
      }
    }
    if (reply.state === "SUBMITTED") {
      setReview(null);
      setEditMode(false);
    }
    if (reply.state === "REVIEW_CONFIRM") {
      setEditMode(false);
    }
    if (typeof reply.data?.receipt === "string") {
      setChat((prev) => [
        ...prev,
        { role: "system", text: `Receipt:\n${reply.data?.receipt as string}` },
      ]);
    }
    if (opts?.playAudio !== false && reply.audio_b64) {
      playServiceAudio(reply.audio_b64, reply.audio_mime);
    }
  }

  async function onStart() {
    setBusy(true);
    setError(null);
    setChat([]);
    setReview(null);
    setTranscript("");
    setEditMode(false);
    setFormDraft({});
    setCapturedFormData({});
    setFormCursorField(null);
    setInvalidFieldName(null);
    setSelectedServiceCode(null);
    stopServiceAudio();
    setServiceAudio(null);
    setServiceAudioState("idle");
    serviceAudioSessionRef.current?.clear();
    try {
      const reply = await startChannel("web");
      pushBot(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start");
    } finally {
      setBusy(false);
    }
  }

  async function sendJourneyText(friendlyLabel: string, text: string): Promise<JourneyResponse | null> {
    if (!applicationId || !token) return null;
    setChat((prev) => [...prev, { role: "user", text: friendlyLabel }]);
    const reply = await sendChannelMessage("web", applicationId, token, {
      text,
      language: normalizeLang(language),
      modality: "text",
    });
    pushBot(reply);
    return reply;
  }

  async function submitCommand(friendlyLabel: string, command: string) {
    if (!applicationId || !token) return;
    setBusy(true);
    setError(null);
    try {
      await sendJourneyText(friendlyLabel, command);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  async function confirmMockPayment(friendlyLabel: string) {
    if (!applicationId || !token || paymentProcessing) return;
    setMockPayOpen(false);
    setPaymentProcessing(true);
    setBusy(true);
    setError(null);
    try {
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      await sendJourneyText(friendlyLabel, JOURNEY_COMMANDS.pay);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Payment failed");
    } finally {
      setPaymentProcessing(false);
      setBusy(false);
    }
  }

  function updateDraft(fieldName: string, value: string) {
    setFormDraft((prev) => ({ ...prev, [fieldName]: value }));
    setInvalidFieldName((prev) => (prev === fieldName ? null : prev));
  }

  function focusFormField(fieldName: string, prefix: "field" | "edit" = "field") {
    setInvalidFieldName(fieldName);
    window.requestAnimationFrame(() => {
      const el = document.getElementById(`${prefix}-${fieldName}`);
      if (el instanceof HTMLElement) {
        el.focus();
        el.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    });
  }

  function blockIfMissingRequired(prefix: "field" | "edit" = "field"): boolean {
    const missing = findFirstMissingRequired(serviceFields, formDraft);
    if (!missing) return false;
    setError(missingRequiredMessage(missing));
    focusFormField(missing.name, prefix);
    return true;
  }

  async function submitRemainingFormFields() {
    if (!applicationId || !token || !serviceFields.length) return;
    if (blockIfMissingRequired("field")) return;
    setBusy(true);
    setError(null);
    setInvalidFieldName(null);
    try {
      let guard = 0;
      // Always continue from the backend-expected field — never restart at field[0].
      let currentNext = nextField || serviceFields[0]?.name || null;
      while (guard < serviceFields.length + 2) {
        guard += 1;
        if (!currentNext) break;
        const field = serviceFields.find((item) => item.name === currentNext);
        if (!field) break;
        const backendValue = draftValueForBackend(field, formDraft[field.name] || "");
        if (!backendValue) {
          if (field.required) {
            setError(missingRequiredMessage(field));
            focusFormField(field.name);
            return;
          }
          break;
        }
        // Do not replay values the backend already recorded.
        const prior = capturedFormData[field.name];
        if (prior != null && String(prior) === backendValue) {
          const idx = serviceFields.findIndex((item) => item.name === field.name);
          currentNext = serviceFields[idx + 1]?.name || null;
          continue;
        }
        const reply = await sendJourneyText(
          `${citizenFieldCaption(field)}: ${backendValue}`,
          backendValue,
        );
        if (!reply) return;
        if (reply.error === "validation_failed") {
          setError(reply.message || `Please check ${citizenFieldCaption(field)}.`);
          setFormCursorField(field.name);
          focusFormField(field.name);
          return;
        }
        if (reply.state !== "FORM_CAPTURE") break;
        currentNext =
          typeof reply.data?.next_field === "string" ? reply.data.next_field : null;
        if (currentNext) setFormCursorField(currentNext);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the form");
    } finally {
      setBusy(false);
    }
  }

  async function saveEditedDetails() {
    if (!applicationId || !token || !serviceFields.length || !review?.fields) return;
    if (blockIfMissingRequired("edit")) return;
    setBusy(true);
    setError(null);
    setInvalidFieldName(null);
    try {
      const original = review.fields;
      for (const field of serviceFields) {
        const backendValue = draftValueForBackend(field, formDraft[field.name] || "");
        const previous = String(original[field.name] ?? "");
        if (!backendValue) {
          if (field.required) {
            setError(missingRequiredMessage(field));
            focusFormField(field.name, "edit");
            return;
          }
          continue;
        }
        if (backendValue === previous) continue;

        let reply = await sendJourneyText("Edit details", JOURNEY_COMMANDS.correct);
        if (!reply || reply.state !== "CORRECTION") {
          setError("Could not start editing. Please try again.");
          return;
        }
        reply = await sendJourneyText(citizenFieldCaption(field), field.name);
        if (!reply || reply.error) {
          setError(reply?.message || `Could not select ${citizenFieldCaption(field)}.`);
          return;
        }
        reply = await sendJourneyText(
          `${citizenFieldCaption(field)}: ${backendValue}`,
          backendValue,
        );
        if (!reply || reply.error === "validation_failed") {
          setError(reply?.message || `Please check ${citizenFieldCaption(field)}.`);
          focusFormField(field.name, "edit");
          return;
        }
      }
      setEditMode(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save changes");
    } finally {
      setBusy(false);
    }
  }

  function startEditDetails() {
    if (review?.fields && serviceFields.length) {
      setFormDraft(draftFromCaptured(serviceFields, review.fields));
    } else if (serviceFields.length) {
      setFormDraft(emptyDraft(serviceFields));
    }
    setEditMode(true);
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
        language: normalizeLang(language),
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
    const lang = normalizeLang(code);
    setLanguage(lang);
    if (!applicationId || !token) return;

    // Language buttons only submit during language selection.
    // Otherwise a later "English" click was sending junk into form capture / voice flows.
    if (state !== "LANGUAGE_SELECT") {
      setChat((prev) => [
        ...prev,
        {
          role: "system",
          text: `UI language preference set to ${lang}. Journey language was already chosen.`,
        },
      ]);
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const reply = await sendChannelMessage("web", applicationId, token, {
        text: lang,
        language: lang,
        modality: "text",
      });
      setChat((prev) => [...prev, { role: "user", text: `Language: ${lang}` }]);
      pushBot(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Language failed");
    } finally {
      setBusy(false);
    }
  }

  async function submitVoice(opts: {
    audio_b64?: string;
    transcript?: string;
    note: string;
    userLabel: string;
  }) {
    if (!applicationId || !token) return;
    const lang = normalizeLang(language);
    setVoicePhase("processing");
    setBusy(true);
    setError(null);
    setVoiceNote("Processing speech…");
    setChat((prev) => [
      ...prev,
      { role: "system", text: opts.note },
      { role: "user", text: opts.userLabel },
    ]);
    setVoiceNote(opts.note);
    try {
      const reply = await sendChannelMessage("web", applicationId, token, {
        modality: "voice",
        language: lang,
        audio_b64: opts.audio_b64,
        transcript: opts.transcript,
      });
      if (reply.transcript) setTranscript(reply.transcript);
      else if (opts.transcript) setTranscript(opts.transcript);
      if (reply.transcript && !opts.transcript) {
        setChat((prev) => {
          const updated = [...prev];
          for (let i = updated.length - 1; i >= 0; i--) {
            if (updated[i].role === "user" && updated[i].text === opts.userLabel) {
              updated[i] = { role: "user", text: reply.transcript as string };
              break;
            }
          }
          return updated;
        });
      }
      pushBot(reply);
      if (reply.error === "stt_unrecognized") {
        setError(
          reply.message ||
            "I couldn't understand the recording. Please speak clearly and try again.",
        );
      } else if (reply.error === "invalid_language" || reply.error === "language_ambiguous") {
        setError(reply.message || "Please choose your preferred language and try again.");
      } else if (reply.error === "unknown_mobile") {
        setError(
          reply.message ||
            "I couldn't recognise that mobile number. Please say the 10-digit number clearly and try again.",
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Voice failed");
    } finally {
      setBusy(false);
      setVoicePhase("idle");
      setVoiceNote(null);
    }
  }

  async function finishRecording() {
    const recorder = mediaRef.current;
    const stream = streamRef.current;
    mediaRef.current = null;
    streamRef.current = null;
    setVoicePhase("processing");
    setVoiceNote("Processing speech…");

    const chunks = chunksRef.current;
    chunksRef.current = [];
    const typed = typedAtRecordStart.current.trim();
    typedAtRecordStart.current = "";

    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
    }

    if (!chunks.length) {
      setVoicePhase("idle");
      setVoiceNote(null);
      setError("No audio captured. Allow the microphone and try Speak again.");
      return;
    }

    const mime = recorder?.mimeType || "audio/webm";
    const blob = new Blob(chunks, { type: mime });
    if (blob.size < 32) {
      setVoicePhase("idle");
      setVoiceNote(null);
      setError("Recording was empty. Hold Speak longer, or type your reply and use Send.");
      return;
    }

    try {
      const audio_b64 = await recordingBlobToWavBase64(blob);
      if (typed) {
        await submitVoice({
          audio_b64,
          transcript: typed,
          note:
            "Microphone audio sent locally. Mock STT fallback: using your typed phrase as the transcript.",
          userLabel: `Voice (mock STT): ${typed}`,
        });
        setInput("");
      } else {
        await submitVoice({
          audio_b64,
          note: "Sending recording to local speech recognition…",
          userLabel: "Voice message",
        });
      }
    } catch (err) {
      setVoicePhase("idle");
      setVoiceNote(null);
      setError(err instanceof Error ? err.message : "Could not process recording");
    }
  }

  async function toggleRecord() {
    if (isListening && mediaRef.current) {
      setVoicePhase("processing");
      setVoiceNote("Processing speech…");
      mediaRef.current.stop();
      // Do not restart previous service TTS after the citizen stops recording.
      return;
    }
    if (!applicationId || !token || isVoiceProcessing) return;
    setError(null);
    setVoiceNote(null);

    // Barge-in: stop service TTS immediately before the microphone opens.
    serviceAudioSessionRef.current?.interruptForRecording();
    setServiceAudioState("idle");

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimePreferred = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : undefined;
      const recorder = mimePreferred
        ? new MediaRecorder(stream, { mimeType: mimePreferred })
        : new MediaRecorder(stream);
      chunksRef.current = [];
      typedAtRecordStart.current = input;
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        void finishRecording();
      };
      mediaRef.current = recorder;
      recorder.start(200);
      setVoicePhase("listening");
      setVoiceNote("Listening… speak now, then press Stop.");
    } catch {
      // Permission denied or no mic — explicit mock path only if user typed a phrase
      const typed = input.trim();
      if (typed) {
        await submitVoice({
          audio_b64: encodePocVoice(typed),
          transcript: typed,
          note:
            "Microphone unavailable or denied. Mock STT fallback: sending typed phrase as POC voice marker (local only).",
          userLabel: `Voice (mock, no mic): ${typed}`,
        });
        setInput("");
      } else {
        setError(
          "Microphone permission denied. Allow the mic, or type your reply and press Speak (mock STT) / Send.",
        );
      }
    }
  }

  async function onConsent(granted: boolean) {
    if (!applicationId || !token) return;
    setBusy(true);
    try {
      const reply = await postConsent(applicationId, token, granted);
      setChat((prev) => [
        ...prev,
        { role: "user", text: granted ? "I Agree" : "Decline" },
      ]);
      pushBot(reply);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Consent failed");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(categoryCode: string) {
    const file = pendingFiles[categoryCode];
    const docMeta = serviceDocuments.find((d) => d.code === categoryCode);
    const accepted = docMeta?.accepted_types || [];
    const docType = selectedDocTypes[categoryCode] || accepted[0]?.code;
    if (!file || !applicationId || !token || !categoryCode) return;
    if (accepted.length > 0 && !docType) {
      setError("Choose a document type before uploading.");
      return;
    }
    setDocCode(categoryCode);
    setBusy(true);
    const categoryLabel = docMeta?.label || documentLabel(categoryCode);
    const typeLabel =
      accepted.find((t) => t.code === docType)?.label || docType || "document";
    setChat((prev) => [
      ...prev,
      { role: "user", text: `Upload ${categoryLabel} (${typeLabel}): ${file.name}` },
    ]);
    try {
      const reply = await uploadDocument(
        applicationId,
        token,
        categoryCode,
        file,
        docType,
      );
      pushBot(reply);
      setPendingFiles((prev) => ({ ...prev, [categoryCode]: null }));
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
      <div className="journey-hero">
        <div className="journey-header">
          <div>
            <h1>Apply for an Income Certificate</h1>
            <p className="lede">
              Complete your application by voice or text. You can speak in English, हिन्दी, or
              ಕನ್ನಡ.
            </p>
          </div>
          {(applicationId || (state && state !== "—")) && (
            <div className="journey-meta" aria-live="polite">
              <div>
                <span className="label">Application ID</span>
                <strong>{applicationId ?? "Not started"}</strong>
              </div>
              <div>
                <span className="label">Step</span>
                <strong className="state-pill">{stateLabel(state)}</strong>
              </div>
              <div>
                <span className="label">Language</span>
                <strong>{languageLabel(language)}</strong>
              </div>
            </div>
          )}
        </div>

        <div className="journey-start-card">
          <div className="journey-start-copy">
            <h2 style={{ margin: 0 }}>Start the application</h2>
            <p>
              Start to hear the welcome message. After that, the service guides you step by
              step — you do not need to type the first question.
            </p>
          </div>
          <div className="journey-actions" style={{ margin: 0 }}>
            <button
              type="button"
              className="btn-primary-lg"
              onClick={() => void onStart()}
              disabled={busy}
            >
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
              Refresh status
            </button>
            {applicationId && token && (
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() => {
                  storeSessionHandoff(applicationId, token);
                  navigate("/whatsapp", {
                    state: {
                      resumeFromWeb: true,
                      applicationId,
                    } satisfies WhatsAppResumeNavState,
                  });
                }}
              >
                Continue on WhatsApp
              </button>
            )}
          </div>
        </div>

        <div className="lang-pills" role="group" aria-label="Select language" style={{ marginTop: "1.25rem" }}>
          <span className="lang-label">Language</span>
          {languages.map((l) => (
            <button
              key={l.code}
              type="button"
              aria-pressed={language === l.code}
              disabled={busy || !applicationId || state !== "LANGUAGE_SELECT"}
              onClick={() => void sendLanguage(l.code)}
            >
              {l.native_name}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {(voiceNote || isServicePlaying) && (
        <p
          className={`meta voice-status${isListening ? " voice-status-listening" : isVoiceProcessing ? " voice-status-processing" : isServicePlaying ? " voice-status-playing" : ""}`}
          role="status"
        >
          {isListening && (
            <span className="voice-recording-indicator" aria-hidden="true">
              <span className="voice-recording-dot" />
              <span className="voice-recording-pulse" />
            </span>
          )}
          {isServicePlaying && !isListening && !isVoiceProcessing
            ? "Voice: Playing…"
            : voiceNote
              ? <>Voice: <em>{voiceNote}</em></>
              : null}
        </p>
      )}
      {transcript && (
        <p className="meta">
          Last voice transcript: <em>{transcript}</em>
        </p>
      )}

      {(serviceAudioState === "playing" || serviceAudioState === "blocked" || serviceAudio) && (
        <div className="service-audio-bar" role="region" aria-label="Service audio response">
          {serviceAudioState === "playing" && (
            <p className="meta service-audio-status" role="status">
              Playing audio response…
            </p>
          )}
          {serviceAudioState === "blocked" && (
            <p className="meta service-audio-status" role="status">
              Tap Play to hear the instruction.
            </p>
          )}
          {serviceAudio && (
            <button
              type="button"
              className="ghost service-audio-replay"
              onClick={replayServiceAudio}
              aria-label="Replay service audio response"
            >
              {serviceAudioState === "playing" ? "Replay" : "Play"}
            </button>
          )}
        </div>
      )}

      <div className="conversation-panel">
        <h2>Conversation</h2>
        <div className="chat-log" role="log" aria-live="polite" aria-relevant="additions">
          {chat.length === 0 && (
            <div className="bubble system">
              Press <strong>Start application</strong> to hear the welcome prompt, then use{" "}
              <strong>Speak</strong> to reply by voice. You can also type as a fallback. The
              service speaks each next step — no need to type the question.
            </div>
          )}
          {chat.map((item, idx) => {
            const isLatestBot =
              item.role === "bot" && idx === chat.map((c) => c.role).lastIndexOf("bot");
            return (
              <div
                key={`${item.role}-${idx}`}
                className={`bubble ${item.role}${isLatestBot ? " latest-prompt" : ""}`}
              >
                <span className="bubble-role">
                  {item.role === "user" ? "You" : item.role === "bot" ? "Service" : "Notice"}
                </span>
                {item.text}
              </div>
            );
          })}
          <div ref={chatEndRef} />
        </div>

        {state === "CONSENT" && (
          <div className="action-bar consent-bar" role="group" aria-label="Consent">
            <p className="action-bar-lead">
              Please confirm consent to continue your application.
            </p>
            <div className="action-bar-buttons">
              <button
                type="button"
                className="btn-success"
                onClick={() => void onConsent(true)}
                disabled={busy}
              >
                I Agree
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
          </div>
        )}

        {showsFieldConfirmationActions(state) && (
          <div
            className="action-bar field-confirm-bar"
            role="group"
            aria-label="Confirm captured value"
          >
            <p className="action-bar-lead">Please confirm what the service heard.</p>
            <div className="action-bar-buttons">
              <button
                type="button"
                className="btn-success"
                disabled={busy}
                onClick={() =>
                  void submitCommand("Yes, correct", JOURNEY_COMMANDS.fieldConfirmYes)
                }
              >
                Yes, correct
              </button>
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() =>
                  void submitCommand("No, try again", JOURNEY_COMMANDS.fieldConfirmNo)
                }
              >
                No, try again
              </button>
            </div>
          </div>
        )}

        {state === "SERVICE_SELECT" && services.length > 0 && (
          <div className="action-bar service-bar" role="group" aria-label="Choose a service">
            <p className="action-bar-lead">Select the service you would like to apply for.</p>
            <div className="service-cards">
              {services.map((service) => {
                const applyLabel = applyForServiceLabel(service.display_name);
                return (
                  <article key={service.code} className="service-card">
                    <h3 className="service-card-title">{service.display_name}</h3>
                    {service.description && (
                      <p className="service-card-desc">{service.description.trim()}</p>
                    )}
                    <button
                      type="button"
                      className="btn-success service-apply-btn"
                      disabled={busy}
                      aria-label={applyLabel}
                      onClick={() => {
                        setSelectedServiceCode(service.code);
                        setFormDraft(emptyDraft(service.fields || []));
                        void submitCommand(applyLabel, service.code);
                      }}
                    >
                      {applyLabel}
                    </button>
                  </article>
                );
              })}
            </div>
          </div>
        )}

        {state === "FORM_CAPTURE" && serviceFields.length > 0 && !editMode && (
          <form
            className="action-bar application-form"
            aria-label="Application form"
            onSubmit={(e) => {
              e.preventDefault();
              void submitRemainingFormFields();
            }}
          >
            <h3 className="form-title">
              {serviceDisplayName(activeService?.code, services)} application
            </h3>
            <p className="action-bar-lead">
              Fill in the details below, or answer by voice using Speak.
            </p>
            <div className="form-grid">
              {serviceFields.map((field) => {
                const inputType = fieldInputType(field);
                const isDate = inputType === "date";
                const invalid = invalidFieldName === field.name;
                return (
                  <label
                    key={field.name}
                    className={`form-field${invalid ? " form-field-invalid" : ""}`}
                    htmlFor={`field-${field.name}`}
                  >
                    {citizenFieldCaption(field)}
                    {field.required ? <span className="required-mark"> *</span> : null}
                    <input
                      id={`field-${field.name}`}
                      type={inputType}
                      inputMode={fieldInputMode(field)}
                      value={formDraft[field.name] || ""}
                      max={isDate ? todayIso : undefined}
                      disabled={busy}
                      autoComplete="off"
                      aria-required={field.required}
                      aria-invalid={invalid}
                      className={invalid ? "field-invalid" : undefined}
                      onChange={(e) => updateDraft(field.name, e.target.value)}
                    />
                  </label>
                );
              })}
            </div>
            <div className="action-bar-buttons">
              <button type="submit" className="btn-success" disabled={busy}>
                Save and continue
              </button>
            </div>
          </form>
        )}

        {state === "CORRECTION" && serviceFields.length > 0 && (
          <div className="action-bar" role="group" aria-label="Choose a detail to edit">
            <p className="action-bar-lead">Which detail would you like to change?</p>
            <div className="action-bar-buttons">
              {serviceFields.map((field) => (
                <button
                  key={field.name}
                  type="button"
                  className="ghost"
                  disabled={busy}
                  onClick={() =>
                    void submitCommand(citizenFieldCaption(field), field.name)
                  }
                >
                  {citizenFieldCaption(field)}
                </button>
              ))}
            </div>
          </div>
        )}

        {state === "REVIEW_CONFIRM" && review && !editMode && (
          <article className="review-card citizen-review" aria-label="Application review">
            <h3>Review your application</h3>
            <p className="review-service">
              Service:{" "}
              <strong>
                {serviceDisplayName(review.service || activeService?.code, services)}
              </strong>
            </p>
            {review.fields && Object.keys(review.fields).length > 0 && (
              <dl className="review-fields">
                {Object.entries(review.fields).map(([key, value]) => (
                  <div key={key} className="review-field-row">
                    <dt>{fieldLabel(key)}</dt>
                    <dd>{String(value ?? "—")}</dd>
                  </div>
                ))}
              </dl>
            )}
            {review.documents && review.documents.length > 0 && (
              <div className="review-documents">
                <h4>Uploaded documents</h4>
                <ul>
                  {review.documents.map((doc) => (
                    <li key={doc.code}>
                      <strong>
                        {serviceDocuments.find((item) => item.code === doc.code)?.label ||
                          documentLabel(doc.code)}
                      </strong>
                      {doc.filename ? ` — ${doc.filename}` : ""}
                      {doc.verification_status ? (
                        <span
                          className="review-doc-status"
                          title={VERIFICATION_POC_NOTE}
                        >
                          {" "}
                          — {verificationStatusLabel(doc.verification_status)}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="action-bar-buttons review-actions">
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={startEditDetails}
              >
                Edit details
              </button>
              <button
                type="button"
                className="btn-success"
                disabled={busy}
                onClick={() =>
                  void submitCommand("Continue to payment", JOURNEY_COMMANDS.confirm)
                }
              >
                Continue to payment
              </button>
            </div>
          </article>
        )}

        {state === "REVIEW_CONFIRM" && editMode && serviceFields.length > 0 && (
          <form
            className="action-bar application-form"
            aria-label="Edit application details"
            onSubmit={(e) => {
              e.preventDefault();
              void saveEditedDetails();
            }}
          >
            <h3 className="form-title">Edit details</h3>
            <p className="action-bar-lead">
              Update any fields below, then save. Unchanged details are left as they are.
            </p>
            <div className="form-grid">
              {serviceFields.map((field) => {
                const inputType = fieldInputType(field);
                const isDate = inputType === "date";
                const invalid = invalidFieldName === field.name;
                return (
                  <label
                    key={field.name}
                    className={`form-field${invalid ? " form-field-invalid" : ""}`}
                    htmlFor={`edit-${field.name}`}
                  >
                    {citizenFieldCaption(field)}
                    {field.required ? <span className="required-mark"> *</span> : null}
                    <input
                      id={`edit-${field.name}`}
                      type={inputType}
                      inputMode={fieldInputMode(field)}
                      value={formDraft[field.name] || ""}
                      max={isDate ? todayIso : undefined}
                      disabled={busy}
                      autoComplete="off"
                      aria-required={field.required}
                      aria-invalid={invalid}
                      className={invalid ? "field-invalid" : undefined}
                      onChange={(e) => updateDraft(field.name, e.target.value)}
                    />
                  </label>
                );
              })}
            </div>
            <div className="action-bar-buttons">
              <button type="submit" className="btn-success" disabled={busy}>
                Save changes
              </button>
              <button
                type="button"
                className="ghost"
                disabled={busy}
                onClick={() => setEditMode(false)}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {showPaymentActions && state === "FEE_QUOTE" && feeInfo && (
          <div className="action-bar payment-quote-bar" role="group" aria-label="Application fee">
            <p className="fee-summary">
              Application fee
              <strong className="fee-amount">{feeInfo.display}</strong>
            </p>
            <div className="action-bar-buttons">
              <button
                type="button"
                className="btn-success"
                disabled={busy || paymentProcessing}
                onClick={() =>
                  void submitCommand("Proceed to payment", JOURNEY_COMMANDS.pay)
                }
              >
                Proceed to payment
              </button>
              <button
                type="button"
                className="ghost"
                disabled={busy || paymentProcessing}
                onClick={() => void submitCommand("Cancel", JOURNEY_COMMANDS.cancel)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {showPaymentActions && state === "PAYMENT" && feeInfo && (
          <div className="payment-mock-card" role="region" aria-label="Mock payment">
            <div className="payment-mock-header">
              <h3>Pay application fee</h3>
              <span className="demo-badge">SYNTHETIC / DEMO</span>
            </div>
            <dl className="payment-mock-dl">
              <dt>Amount</dt>
              <dd>{feeInfo.display}</dd>
              <dt>Payment method</dt>
              <dd>QR Code</dd>
            </dl>

            {paymentProcessing ? (
              <p className="payment-processing" role="status">
                Processing payment…
              </p>
            ) : (
              <>
                <div className="demo-qr" aria-label="Synthetic demo QR code">
                  <svg viewBox="0 0 120 120" width="140" height="140" role="img">
                    <title>Synthetic demo QR code — not a real payment code</title>
                    <rect width="120" height="120" fill="#fff" stroke="#1a5f9e" strokeWidth="4" />
                    <rect x="12" y="12" width="28" height="28" fill="#1a2332" />
                    <rect x="80" y="12" width="28" height="28" fill="#1a2332" />
                    <rect x="12" y="80" width="28" height="28" fill="#1a2332" />
                    <rect x="48" y="48" width="24" height="24" fill="#1a2332" />
                    <rect x="80" y="80" width="12" height="12" fill="#1a2332" />
                    <rect x="100" y="80" width="8" height="8" fill="#1a2332" />
                    <rect x="80" y="100" width="8" height="8" fill="#1a2332" />
                    <rect x="52" y="16" width="8" height="8" fill="#1a2332" />
                    <rect x="16" y="52" width="8" height="8" fill="#1a2332" />
                    <rect x="64" y="80" width="8" height="20" fill="#1a2332" />
                    <text
                      x="60"
                      y="72"
                      textAnchor="middle"
                      fontSize="9"
                      fill="#1a5f9e"
                      fontFamily="system-ui,sans-serif"
                      fontWeight="700"
                    >
                      DEMO
                    </text>
                  </svg>
                  <p className="muted demo-qr-caption">
                    Demo QR only — no real UPI or gateway charge
                  </p>
                </div>

                <div className="action-bar-buttons payment-mock-actions">
                  <button
                    type="button"
                    className="ghost"
                    disabled={busy}
                    onClick={() => setMockPayOpen(true)}
                  >
                    Open payment link
                  </button>
                  <button
                    type="button"
                    className="btn-success"
                    disabled={busy}
                    onClick={() => void confirmMockPayment("I have paid")}
                  >
                    I have paid
                  </button>
                  <button
                    type="button"
                    className="ghost"
                    disabled={busy}
                    onClick={() => void submitCommand("Cancel", JOURNEY_COMMANDS.cancel)}
                  >
                    Cancel
                  </button>
                </div>
              </>
            )}

            {mockPayOpen && !paymentProcessing && (
              <div
                className="mock-pay-modal"
                role="dialog"
                aria-modal="true"
                aria-labelledby="mock-pay-title"
              >
                <div className="mock-pay-modal-card">
                  <h4 id="mock-pay-title">Demo payment page</h4>
                  <p className="muted">
                    Local synthetic checkout — no external payment API is called.
                  </p>
                  <p className="fee-summary">
                    Amount due <strong>{feeInfo.display}</strong>
                  </p>
                  <p className="meta">
                    Link:{" "}
                    <code>https://pay.local/demo/{applicationId || "INC"}</code>
                  </p>
                  <div className="action-bar-buttons">
                    <button
                      type="button"
                      className="btn-success"
                      onClick={() => void confirmMockPayment("Paid via demo link")}
                    >
                      Confirm demo payment
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setMockPayOpen(false)}
                    >
                      Close
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {showPaymentActions && state === "PAYMENT_FAILED" && feeInfo && (
          <div className="action-bar payment-sim-bar" role="group" aria-label="Retry payment">
            <p className="action-bar-lead">
              Payment did not complete. No fee was charged. You can try again.
            </p>
            <div className="action-bar-buttons">
              <button
                type="button"
                className="btn-success"
                disabled={busy || paymentProcessing}
                onClick={() => void submitCommand("Retry payment", JOURNEY_COMMANDS.retry)}
              >
                Retry payment
              </button>
              <button
                type="button"
                className="ghost"
                disabled={busy || paymentProcessing}
                onClick={() => void submitCommand("Cancel", JOURNEY_COMMANDS.cancel)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {(state === "DOCUMENT_CAPTURE" || state === "DOCUMENT_REJECTED") && (
          <div className="upload-bar" aria-label="Document upload">
            <p className="action-bar-lead">
              Upload the required documents (PDF, JPG, or PNG). Use synthetic demo files for this
              POC.
            </p>
            <div className="doc-card-grid">
              {serviceDocuments.map((doc) => {
                const needed = missingDocs.includes(doc.code);
                const reviewed = review?.documents?.find((d) => d.code === doc.code);
                const statusText = needed
                  ? state === "DOCUMENT_REJECTED"
                    ? "Needs re-upload"
                    : "Required"
                  : reviewed?.verification_status
                    ? verificationStatusLabel(reviewed.verification_status)
                    : "Uploaded";
                const accepted = doc.accepted_types || [];
                const selectedType = selectedDocTypes[doc.code] || accepted[0]?.code || "";
                const pending = pendingFiles[doc.code];
                const acceptAttr = (doc.allowed_mime_types || [])
                  .map((m) => {
                    if (m === "application/pdf") return ".pdf";
                    if (m === "image/jpeg") return ".jpg,.jpeg";
                    if (m === "image/png") return ".png";
                    return "";
                  })
                  .filter(Boolean)
                  .join(",");
                return (
                  <article
                    key={doc.code}
                    className={`doc-card${needed ? " needed" : " done"}`}
                  >
                    <h3>{doc.label || documentLabel(doc.code)}</h3>
                    <span className="doc-status" aria-label={`Status: ${statusText}`}>
                      {statusText}
                    </span>
                    {needed && accepted.length > 0 && (
                      <fieldset className="doc-type-fieldset">
                        <legend>Choose document type</legend>
                        <div className="doc-type-options" role="group">
                          {accepted.map((t) => (
                            <button
                              key={t.code}
                              type="button"
                              className={
                                selectedType === t.code ? "doc-type-btn active" : "doc-type-btn"
                              }
                              aria-pressed={selectedType === t.code}
                              disabled={busy}
                              onClick={() =>
                                setSelectedDocTypes((prev) => ({
                                  ...prev,
                                  [doc.code]: t.code,
                                }))
                              }
                            >
                              {t.label}
                            </button>
                          ))}
                        </div>
                      </fieldset>
                    )}
                    {needed && (
                      <>
                        <label htmlFor={`doc-file-${doc.code}`}>
                          Choose document
                          <input
                            id={`doc-file-${doc.code}`}
                            type="file"
                            accept={acceptAttr || ".pdf,.png,.jpg,.jpeg"}
                            disabled={busy}
                            onChange={(e) => {
                              const file = e.target.files?.[0] ?? null;
                              setPendingFiles((prev) => ({ ...prev, [doc.code]: file }));
                              setDocCode(doc.code);
                            }}
                          />
                        </label>
                        {pending && (
                          <p className="meta">
                            Selected: <strong>{pending.name}</strong>
                          </p>
                        )}
                        <button
                          type="button"
                          disabled={busy || !pending || (accepted.length > 0 && !selectedType)}
                          onClick={() => void onUpload(doc.code)}
                        >
                          Upload document
                        </button>
                      </>
                    )}
                  </article>
                );
              })}
              {serviceDocuments.length === 0 && (
                <p className="muted">Loading document requirements from the service catalogue…</p>
              )}
            </div>
          </div>
        )}

        {state === "SUBMITTED" && (
          <div className="submitted-card" role="status" aria-label="Application submitted">
            {typeof last?.data?.payment_ref === "string" && last.data.payment_ref && (
              <div className="payment-success-banner">
                <p className="payment-success-title">✓ Payment successful</p>
                <dl className="payment-mock-dl">
                  <dt>Amount</dt>
                  <dd>
                    {feeInfo?.display ||
                      (activeService?.fee
                        ? formatFee(activeService.fee.amount_paise, activeService.fee.currency)
                        : "—")}
                  </dd>
                  <dt>Payment reference</dt>
                  <dd>{String(last.data.payment_ref)}</dd>
                </dl>
              </div>
            )}
            <h3>Application submitted successfully</h3>
            <p>
              Your Income Certificate application has been submitted. It is with the revenue
              office for review. Keep your application ID for follow-up.
            </p>
            <div className="submitted-meta">
              <div>
                <span className="label">Application ID</span>
                <strong>{applicationId}</strong>
              </div>
              <div>
                <span className="label">Status</span>
                <strong className="badge badge-success">
                  {typeof last?.data?.processing_status === "string"
                    ? String(last.data.processing_status)
                    : stateLabel(state)}
                </strong>
              </div>
              <div>
                <span className="label">Next step</span>
                <strong>Use Refresh status to check progress</strong>
              </div>
            </div>
            {typeof last?.data?.receipt === "string" && (
              <pre className="code-block" style={{ marginTop: "0.75rem" }}>
                {last.data.receipt as string}
              </pre>
            )}
          </div>
        )}

        {state === "ESCALATED" && (
          <div className="action-bar" role="status" aria-label="Escalated">
            <p className="action-bar-lead">
              Your application is with an officer. Quote your application ID for follow-up.
            </p>
          </div>
        )}

        {showComposer && (
          <>
            <p className="text-fallback-hint">
              Prefer typing? Use the message box as a fallback. Speak remains the primary action.
            </p>
            <form className="composer voice-first" onSubmit={(e) => void onSend(e)}>
              <button
                type="button"
                className={
                  isListening
                    ? "speak-btn listening"
                    : isVoiceProcessing
                      ? "speak-btn processing"
                      : isServicePlaying
                        ? "speak-btn playing"
                        : "speak-btn primary"
                }
                disabled={(busy && !isListening) || !applicationId || isVoiceProcessing}
                onClick={() => void toggleRecord()}
                aria-pressed={isListening}
                aria-busy={isVoiceProcessing}
                aria-label={
                  isListening
                    ? "Stop listening"
                    : isVoiceProcessing
                      ? "Processing speech"
                      : isServicePlaying
                        ? "Playing response — press to speak and interrupt"
                        : "Start voice recording"
                }
              >
                {isListening && (
                  <span className="speak-btn-indicator" aria-hidden="true">
                    <span className="voice-recording-dot" />
                  </span>
                )}
                {isListening
                  ? "Listening…"
                  : isVoiceProcessing
                    ? "Processing…"
                    : isServicePlaying
                      ? "Playing…"
                      : "Speak"}
              </button>
              <label htmlFor="citizen-message" className="visually-hidden">
                Your message
              </label>
              <input
                id="citizen-message"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={
                  isListening
                    ? "Listening… press Stop when finished"
                    : isVoiceProcessing
                      ? "Processing speech…"
                      : "Type a reply (optional fallback)…"
                }
                disabled={busy || !applicationId || isListening}
                aria-label="Your message"
              />
              <button
                type="submit"
                className="send-btn"
                disabled={
                  busy || !applicationId || !input.trim() || isListening || isVoiceProcessing
                }
              >
                Send
              </button>
            </form>
          </>
        )}
      </div>
    </section>
  );

}
