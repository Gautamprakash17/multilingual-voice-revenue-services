/** IVR keypad UX helpers — when to buffer/auto-submit DTMF for the existing channel API. */

export const IVR_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#"] as const;
export type IvrKey = (typeof IVR_KEYS)[number];

export type IvrInputMode =
  | "language"
  | "mobile"
  | "otp"
  | "yes_no"
  | "confirm"
  | "register"
  | "service"
  | "collect"
  | "none";

export type IvrCallPhase = "idle" | "waiting_dtmf" | "waiting_speech" | "processing" | "completed";

export type LanguageMenuItem = {
  code: string;
  display_name: string;
};

export type ServiceMenuItem = {
  code: string;
  display_name: string;
};

export function ivrInputMode(
  state: string | null | undefined,
  authStep: string | null | undefined = "",
): IvrInputMode {
  switch (state) {
    case "LANGUAGE_SELECT":
      return "language";
    case "AUTHENTICATE":
      if (authStep === "otp") return "otp";
      if (authStep === "register_offer") return "register";
      if (authStep === "register_name") return "none";
      return "mobile";
    case "CONSENT":
      return "yes_no";
    case "FIELD_CONFIRMATION":
      return "confirm";
    case "SERVICE_SELECT":
      return "service";
    case "REVIEW_CONFIRM":
    case "FEE_QUOTE":
    case "PAYMENT":
    case "PAYMENT_FAILED":
      return "yes_no";
    case "FORM_CAPTURE":
    case "CORRECTION":
      return "none";
    case "SUBMITTED":
    case "ESCALATED":
    case "AUTH_FAILED":
    case "DOCUMENT_CAPTURE":
    case "DOCUMENT_REJECTED":
      return "none";
    default:
      return "none";
  }
}

export function isDigitKey(key: string): boolean {
  return /^[0-9]$/.test(key);
}

/** Keys that may be appended to the DTMF buffer for the current mode. */
export function acceptsIvrKey(mode: IvrInputMode, key: string): boolean {
  if (mode === "none") return false;
  if (mode === "collect") return isDigitKey(key) || key === "#";
  if (mode === "confirm") return key === "1" || key === "2";
  if (mode === "language" || mode === "yes_no" || mode === "register" || mode === "service") {
    return isDigitKey(key);
  }
  if (mode === "mobile" || mode === "otp") {
    return isDigitKey(key);
  }
  return false;
}

export function appendIvrKey(buffer: string, key: string, mode: IvrInputMode): string {
  if (!acceptsIvrKey(mode, key)) return buffer;
  if (mode === "collect" && key === "#") return buffer;
  if (mode === "mobile" && buffer.length >= 10) return buffer;
  if (mode === "otp" && buffer.length >= 6) return buffer;
  if (mode === "confirm") return key;
  if (
    (mode === "language" || mode === "yes_no" || mode === "register" || mode === "service") &&
    buffer.length >= 1
  ) {
    return key;
  }
  return buffer + key;
}

export function shouldAutoSubmitDtmf(
  mode: IvrInputMode,
  buffer: string,
  key?: string,
): boolean {
  if (!buffer) return false;
  if (
    mode === "language" ||
    mode === "yes_no" ||
    mode === "register" ||
    mode === "service" ||
    mode === "confirm"
  ) {
    return buffer.length >= 1;
  }
  if (mode === "mobile") return buffer.length === 10;
  if (mode === "otp") return buffer.length === 6;
  if (mode === "collect") return key === "#";
  return false;
}

export function ivrCallPhase(opts: {
  inCall: boolean;
  busy: boolean;
  state?: string | null;
  mode?: IvrInputMode;
}): IvrCallPhase {
  if (!opts.inCall) return "idle";
  if (opts.busy) return "processing";
  if (opts.state === "SUBMITTED" || opts.state === "ESCALATED") return "completed";
  const mode = opts.mode ?? ivrInputMode(opts.state);
  if (mode === "none") return "waiting_speech";
  if (mode === "collect") return "waiting_dtmf";
  return "waiting_dtmf";
}

export function ivrCallPhaseLabel(phase: IvrCallPhase): string {
  switch (phase) {
    case "idle":
      return "Idle";
    case "waiting_dtmf":
      return "Waiting for keypad";
    case "waiting_speech":
      return "Listening…";
    case "processing":
      return "Processing";
    case "completed":
      return "Completed";
    default:
      return "Idle";
  }
}

export function formatCallDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

const IVR_KEY_LETTERS: Record<string, string> = {
  "1": "",
  "2": "ABC",
  "3": "DEF",
  "4": "GHI",
  "5": "JKL",
  "6": "MNO",
  "7": "PQRS",
  "8": "TUV",
  "9": "WXYZ",
  "0": "+",
  "*": "",
  "#": "",
};

export function ivrKeyLetters(key: string): string {
  return IVR_KEY_LETTERS[key] ?? "";
}

export function languageSelectIvrPrompt(languages: LanguageMenuItem[]): string {
  const lines = languages.map(
    (lang, index) => `Press ${index + 1} for ${lang.display_name}.`,
  );
  return ["Welcome to Revenue Services.", ...lines].join(" ");
}

export function ivrKeypadHint(
  mode: IvrInputMode,
  opts: {
    languages?: LanguageMenuItem[];
    services?: ServiceMenuItem[];
  } = {},
): string {
  switch (mode) {
    case "language": {
      const langs = opts.languages ?? [];
      if (langs.length === 0) return "Press a number to choose your language.";
      return langs.map((lang, i) => `${i + 1} = ${lang.display_name}`).join(" · ");
    }
    case "mobile":
      return "Enter your 10-digit mobile number on the keypad.";
    case "otp":
      return "Enter the 6-digit OTP on the keypad.";
    case "register":
      return "1 = Register · 2 = Cancel / use another number";
    case "yes_no":
      return "1 = Yes · 2 = No";
    case "confirm":
      return "1 = Confirm · 2 = Change";
    case "service": {
      const services = opts.services ?? [];
      if (services.length === 0) return "Press 1 to continue with the available service.";
      if (services.length === 1) return `1 = ${services[0].display_name}`;
      return services.map((svc, i) => `${i + 1} = ${svc.display_name}`).join(" · ");
    }
    case "collect":
      return "Use the keypad for digits, then # to send — or speak your answer.";
    case "none":
      return "Speak your answer — the microphone opens automatically. Keypad is paused.";
    default:
      return "Speak your answer — the microphone opens automatically.";
  }
}

export function formatIvrDisplay(buffer: string): string {
  return buffer || "—";
}

/** Payload for IVR keypad submissions — never uses the speech/voice modality. */
export function ivrDtmfPayload(digits: string): { modality: "dtmf"; dtmf: string } {
  return { modality: "dtmf", dtmf: digits };
}

/**
 * Align with backend: AUTHENTICATE without an explicit auth_step is the mobile keypad step.
 */
export function resolveIvrAuthStep(
  state: string | null | undefined,
  authStep: string | null | undefined,
): string {
  if (state !== "AUTHENTICATE") return typeof authStep === "string" ? authStep : "";
  if (typeof authStep === "string" && authStep) return authStep;
  return "mobile";
}

/** Derive keypad/speech mode from the latest journey reply (not stale React state). */
export function ivrModeFromJourney(
  state: string | null | undefined,
  authStep: string | null | undefined,
): IvrInputMode {
  return ivrInputMode(state, resolveIvrAuthStep(state, authStep));
}

/**
 * True while a DTMF auto-submit is in flight — buffer must not accept more digits.
 * Prefer a ref (`sending`) so this stays correct across rapid key events.
 */
export function isDtmfSubmitLocked(sending: boolean, busy?: boolean): boolean {
  return Boolean(sending || busy);
}

/** True when the keypad alone drives this step (speech is optional fallback only). */
export function isIvrKeypadDrivenStep(mode: IvrInputMode): boolean {
  return (
    mode === "language" ||
    mode === "mobile" ||
    mode === "otp" ||
    mode === "yes_no" ||
    mode === "confirm" ||
    mode === "register" ||
    mode === "service"
  );
}

/**
 * Free-form voice/simulated-speech steps (registration name, form fields, etc.).
 * Driven by journey state + auth_step via {@link ivrInputMode} — not by field-name hardcoding.
 */
export function isIvrFreeFormSpeechStep(mode: IvrInputMode): boolean {
  return mode === "none";
}

/** True when free-form speech is expected and the speech input must be usable. */
export function isIvrSpeakControlEnabled(opts: {
  speechMode: boolean;
  hasToken: boolean;
  busy: boolean;
}): boolean {
  return opts.speechMode && opts.hasToken && !opts.busy;
}

/** Simulated-speech transcript ready to submit over the existing voice channel. */
export function canSubmitIvrSpeech(transcript: string): boolean {
  return Boolean(transcript.trim());
}

/**
 * Speak button: enabled only with a non-empty transcript (never auto-send empty).
 * The text input stays enabled via {@link isIvrSpeakControlEnabled} so the user can type.
 */
export function isIvrSpeakButtonEnabled(opts: {
  speechMode: boolean;
  hasToken: boolean;
  busy: boolean;
  transcript: string;
}): boolean {
  return isIvrSpeakControlEnabled(opts) && canSubmitIvrSpeech(opts.transcript);
}

/** Primary Speak control label for free-form IVR steps. */
export function ivrSpeakButtonLabel(opts: { busy: boolean; speechMode: boolean }): string {
  if (opts.busy && opts.speechMode) return "Processing…";
  return "Speak";
}

/**
 * True when the UI should show Listening and focus the speech input
 * (in-call free-form step, not while a submit is in flight).
 */
export function shouldAutoEnterIvrListening(opts: {
  inCall: boolean;
  speechMode: boolean;
  busy: boolean;
}): boolean {
  return opts.inCall && opts.speechMode && !opts.busy;
}

/**
 * Simulator "no speech detected" payload — kept for tests / explicit simulation only.
 * The IVR UI must not call the voice API with an empty transcript.
 */
export function ivrNoSpeechPayload(): { modality: "voice"; transcript: string } {
  return { modality: "voice", transcript: " " };
}

/** Payload for IVR simulated speech — never uses the DTMF modality. */
export function ivrVoicePayload(transcript: string): {
  modality: "voice";
  transcript: string;
} {
  return { modality: "voice", transcript };
}

/**
 * Payload for IVR microphone audio — no client transcript so the backend runs local STT.
 */
export function ivrAudioVoicePayload(audio_b64: string): {
  modality: "voice";
  audio_b64: string;
} {
  return { modality: "voice", audio_b64 };
}

/** Preserve AUTHENTICATE auth_step when a reply omits it (e.g. STT unrecognized). */
export function mergeIvrAuthStep(
  state: string | null | undefined,
  incomingAuthStep: string | null | undefined,
  previousAuthStep: string | null | undefined,
): string {
  if (state !== "AUTHENTICATE") {
    return typeof incomingAuthStep === "string" ? incomingAuthStep : "";
  }
  if (typeof incomingAuthStep === "string" && incomingAuthStep) {
    return incomingAuthStep;
  }
  if (typeof previousAuthStep === "string" && previousAuthStep) {
    return previousAuthStep;
  }
  return "mobile";
}

/**
 * Map a physical keyboard event to an on-screen IVR key.
 * Returns null when the key is not part of the telephone keypad.
 */
export function physicalKeyToIvrKey(key: string): IvrKey | null {
  if (key === "*") return "*";
  if (key === "#") return "#";
  if (/^[0-9]$/.test(key)) return key as IvrKey;
  // Some layouts emit Shift+8 as '*' via key; NumpadDigit handled via key "0"-"9".
  return null;
}

/** Ignore laptop-keyboard DTMF while the user is typing in a text field. */
export function shouldIgnoreIvrPhysicalKey(target: EventTarget | null): boolean {
  if (!target || typeof target !== "object") return false;
  const el = target as Partial<HTMLElement> & {
    tagName?: string;
    isContentEditable?: boolean;
    closest?: (selector: string) => Element | null;
  };
  const tag = (el.tagName || "").toUpperCase();
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.isContentEditable) return true;
  if (typeof el.closest === "function") {
    return Boolean(el.closest("input, textarea, select, [contenteditable='true']"));
  }
  return false;
}

/** True when physical keypad digits should feed the existing DTMF handler. */
export function shouldAcceptIvrPhysicalKey(opts: {
  inCall: boolean;
  keypadMode: boolean;
  speechMode: boolean;
  busy?: boolean;
}): boolean {
  if (!opts.inCall || opts.speechMode || !opts.keypadMode) return false;
  if (opts.busy) return false;
  return true;
}

/** Speech-step status shown in the primary IVR call UI. */
export function ivrSpeechListeningLabel(
  listening: boolean,
  busy: boolean,
  opts?: { micActive?: boolean; micDenied?: boolean },
): string {
  if (busy) return "Processing…";
  if (opts?.micDenied) return "Microphone unavailable — use developer fallback";
  if (listening && opts?.micActive) return "Listening…";
  if (listening) return "Listening…";
  return "Speak your answer — keypad is paused for this step";
}
