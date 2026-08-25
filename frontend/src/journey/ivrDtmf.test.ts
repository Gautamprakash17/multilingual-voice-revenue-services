import { describe, expect, it } from "vitest";
import {
  acceptsIvrKey,
  appendIvrKey,
  canSubmitIvrSpeech,
  formatIvrDisplay,
  isDtmfSubmitLocked,
  isIvrFreeFormSpeechStep,
  isIvrKeypadDrivenStep,
  isIvrSpeakButtonEnabled,
  isIvrSpeakControlEnabled,
  ivrCallPhase,
  ivrCallPhaseLabel,
  formatCallDuration,
  ivrKeyLetters,
  ivrDtmfPayload,
  ivrInputMode,
  ivrKeypadHint,
  ivrModeFromJourney,
  ivrNoSpeechPayload,
  ivrSpeakButtonLabel,
  ivrSpeechListeningLabel,
  ivrVoicePayload,
  languageSelectIvrPrompt,
  physicalKeyToIvrKey,
  resolveIvrAuthStep,
  shouldAcceptIvrPhysicalKey,
  shouldAutoEnterIvrListening,
  shouldAutoSubmitDtmf,
  shouldIgnoreIvrPhysicalKey,
} from "./ivrDtmf";
import { ServiceAudioSession, type PlayableAudio } from "./serviceAudio";

describe("IVR start / language DTMF", () => {
  it("formats call duration for the phone header", () => {
    expect(formatCallDuration(0)).toBe("00:00");
    expect(formatCallDuration(75)).toBe("01:15");
  });

  it("shows telephone-style letters under keypad digits", () => {
    expect(ivrKeyLetters("2")).toBe("ABC");
    expect(ivrKeyLetters("7")).toBe("PQRS");
    expect(ivrKeyLetters("1")).toBe("");
    expect(ivrKeyLetters("#")).toBe("");
  });

  it("starts in language mode and builds the press-1/2/3 welcome", () => {
    expect(ivrInputMode("LANGUAGE_SELECT")).toBe("language");
    expect(
      languageSelectIvrPrompt([
        { code: "en", display_name: "English" },
        { code: "hi", display_name: "Hindi" },
        { code: "kn", display_name: "Kannada" },
      ]),
    ).toBe(
      "Welcome to Revenue Services. Press 1 for English. Press 2 for Hindi. Press 3 for Kannada.",
    );
  });

  it("maps language keys 1/2/3 for auto-submit", () => {
    expect(appendIvrKey("", "1", "language")).toBe("1");
    expect(shouldAutoSubmitDtmf("language", "1")).toBe(true);
    expect(appendIvrKey("", "2", "language")).toBe("2");
    expect(shouldAutoSubmitDtmf("language", "2")).toBe(true);
    expect(appendIvrKey("", "3", "language")).toBe("3");
    expect(shouldAutoSubmitDtmf("language", "3")).toBe(true);
  });

  it("still accepts an invalid language key so the backend can retry", () => {
    expect(acceptsIvrKey("language", "4")).toBe(true);
    expect(shouldAutoSubmitDtmf("language", "4")).toBe(true);
  });
});

describe("IVR mobile and OTP keypad", () => {
  it("buffers a mobile number and submits only at 10 digits", () => {
    let buf = "";
    for (const d of "987654321") {
      buf = appendIvrKey(buf, d, "mobile");
      expect(shouldAutoSubmitDtmf("mobile", buf)).toBe(false);
    }
    buf = appendIvrKey(buf, "0", "mobile");
    expect(buf).toBe("9876543210");
    expect(shouldAutoSubmitDtmf("mobile", buf)).toBe(true);
  });

  it("does not submit incomplete mobile numbers", () => {
    expect(shouldAutoSubmitDtmf("mobile", "98765")).toBe(false);
    expect(shouldAutoSubmitDtmf("mobile", "987654321")).toBe(false);
  });

  it("does not grow past 10 mobile digits", () => {
    expect(appendIvrKey("9876543210", "1", "mobile")).toBe("9876543210");
  });

  it("buffers OTP and submits at 6 digits", () => {
    let buf = "";
    for (const d of "58321") {
      buf = appendIvrKey(buf, d, "otp");
      expect(shouldAutoSubmitDtmf("otp", buf)).toBe(false);
    }
    buf = appendIvrKey(buf, "4", "otp");
    expect(buf).toBe("583214");
    expect(shouldAutoSubmitDtmf("otp", buf)).toBe(true);
  });

  it("clears display buffer via empty string", () => {
    expect(formatIvrDisplay("720")).toBe("720");
    expect(formatIvrDisplay("")).toBe("—");
  });

  it("sends keypad mobile/OTP with modality dtmf, not voice", () => {
    expect(ivrDtmfPayload("9876543210")).toEqual({
      modality: "dtmf",
      dtmf: "9876543210",
    });
    expect(ivrDtmfPayload("041927")).toEqual({ modality: "dtmf", dtmf: "041927" });
  });
});

describe("IVR auth / consent / service modes", () => {
  it("defaults AUTHENTICATE without auth_step to mobile keypad mode", () => {
    expect(resolveIvrAuthStep("AUTHENTICATE", "")).toBe("mobile");
    expect(resolveIvrAuthStep("AUTHENTICATE", undefined)).toBe("mobile");
    expect(ivrInputMode("AUTHENTICATE", resolveIvrAuthStep("AUTHENTICATE", ""))).toBe(
      "mobile",
    );
  });

  it("uses existing-account OTP mode after mobile", () => {
    expect(ivrInputMode("AUTHENTICATE", "otp")).toBe("otp");
    expect(ivrInputMode("AUTHENTICATE", "mobile")).toBe("mobile");
    expect(ivrInputMode("AUTHENTICATE", "")).toBe("mobile");
  });

  it("uses registration DTMF yes/no keys", () => {
    expect(ivrInputMode("AUTHENTICATE", "register_offer")).toBe("register");
    expect(ivrKeypadHint("register")).toContain("1 = Register");
    expect(ivrKeypadHint("register")).toContain("2 = Cancel");
    expect(isIvrKeypadDrivenStep("register")).toBe(true);
    expect(isIvrFreeFormSpeechStep("register")).toBe(false);
    expect(shouldAutoSubmitDtmf("register", "1")).toBe(true);
    expect(shouldAutoSubmitDtmf("register", "2")).toBe(true);
  });

  it("uses FIELD_CONFIRMATION as 1/2 confirm mode, not #/*", () => {
    expect(ivrInputMode("FIELD_CONFIRMATION")).toBe("confirm");
    expect(ivrKeypadHint("confirm")).toBe("1 = Confirm · 2 = Change");
    expect(acceptsIvrKey("confirm", "1")).toBe(true);
    expect(acceptsIvrKey("confirm", "2")).toBe(true);
    expect(acceptsIvrKey("confirm", "#")).toBe(false);
    expect(acceptsIvrKey("confirm", "*")).toBe(false);
    expect(acceptsIvrKey("mobile", "#")).toBe(false);
    expect(acceptsIvrKey("mobile", "*")).toBe(false);
    expect(acceptsIvrKey("otp", "#")).toBe(false);
    expect(shouldAutoSubmitDtmf("confirm", "1")).toBe(true);
    expect(shouldAutoSubmitDtmf("confirm", "2")).toBe(true);
    expect(isIvrKeypadDrivenStep("confirm")).toBe(true);
  });

  it("uses yes/no DTMF for consent", () => {
    expect(ivrInputMode("CONSENT")).toBe("yes_no");
    expect(ivrKeypadHint("yes_no")).toBe("1 = Yes · 2 = No");
    expect(shouldAutoSubmitDtmf("yes_no", "1")).toBe(true);
    expect(shouldAutoSubmitDtmf("yes_no", "2")).toBe(true);
  });

  it("builds service hints from the catalogue", () => {
    expect(ivrInputMode("SERVICE_SELECT")).toBe("service");
    expect(
      ivrKeypadHint("service", {
        services: [{ code: "INCOME_CERTIFICATE", display_name: "Income Certificate" }],
      }),
    ).toBe("1 = Income Certificate");
  });

  it("marks language/mobile/otp/register/consent as keypad-driven", () => {
    expect(isIvrKeypadDrivenStep("language")).toBe(true);
    expect(isIvrKeypadDrivenStep("mobile")).toBe(true);
    expect(isIvrKeypadDrivenStep("otp")).toBe(true);
    expect(isIvrKeypadDrivenStep("register")).toBe(true);
    expect(isIvrKeypadDrivenStep("yes_no")).toBe(true);
    expect(isIvrKeypadDrivenStep("none")).toBe(false);
  });
});

describe("IVR call phase and speech fallback", () => {
  it("reports waiting / processing / completed phases", () => {
    expect(ivrCallPhase({ inCall: false, busy: false })).toBe("idle");
    expect(ivrCallPhase({ inCall: true, busy: true, state: "AUTHENTICATE" })).toBe(
      "processing",
    );
    expect(
      ivrCallPhase({ inCall: true, busy: false, state: "LANGUAGE_SELECT" }),
    ).toBe("waiting_dtmf");
    expect(
      ivrCallPhase({ inCall: true, busy: false, state: "AUTHENTICATE", mode: "none" }),
    ).toBe("waiting_speech");
    expect(ivrCallPhase({ inCall: true, busy: false, state: "SUBMITTED" })).toBe(
      "completed",
    );
    expect(ivrCallPhaseLabel("waiting_dtmf")).toBe("Waiting for keypad");
    expect(ivrCallPhaseLabel("waiting_speech")).toBe("Listening…");
  });

  it("keeps register_name and free-form steps on simulated speech", () => {
    expect(ivrInputMode("AUTHENTICATE", "register_name")).toBe("none");
    expect(ivrInputMode("FORM_CAPTURE")).toBe("none");
    expect(acceptsIvrKey("none", "1")).toBe(false);
    expect(ivrKeypadHint("none")).toContain("microphone");
    expect(isIvrFreeFormSpeechStep("none")).toBe(true);
    expect(isIvrKeypadDrivenStep("none")).toBe(false);
  });

  it("after registration OTP, free-form name input becomes available (not DTMF)", () => {
    const step = resolveIvrAuthStep("AUTHENTICATE", "register_name");
    const mode = ivrInputMode("AUTHENTICATE", step);
    expect(step).toBe("register_name");
    expect(mode).toBe("none");
    expect(isIvrFreeFormSpeechStep(mode)).toBe(true);
    expect(isIvrKeypadDrivenStep(mode)).toBe(false);
    expect(shouldAutoSubmitDtmf(mode, "Gautam")).toBe(false);
    expect(ivrVoicePayload("Gautam Prakash")).toEqual({
      modality: "voice",
      transcript: "Gautam Prakash",
    });
    expect(ivrDtmfPayload("Gautam Prakash").modality).toBe("dtmf");
  });

  it("enables Speak in register_name even before the transcript is typed", () => {
    const mode = ivrInputMode("AUTHENTICATE", "register_name");
    expect(
      isIvrSpeakControlEnabled({ speechMode: isIvrFreeFormSpeechStep(mode), hasToken: true, busy: false }),
    ).toBe(true);
    expect(canSubmitIvrSpeech("")).toBe(false);
    expect(canSubmitIvrSpeech("Gautam Prakash")).toBe(true);
    // Empty transcript must not enable Speak / voice API submit.
    expect(
      isIvrSpeakButtonEnabled({
        speechMode: true,
        hasToken: true,
        busy: false,
        transcript: "",
      }),
    ).toBe(false);
    expect(
      isIvrSpeakButtonEnabled({
        speechMode: true,
        hasToken: true,
        busy: false,
        transcript: "Gautam Prakash",
      }),
    ).toBe(true);
    expect(ivrSpeakButtonLabel({ busy: false, speechMode: true })).toBe("Speak");
    expect(ivrSpeakButtonLabel({ busy: true, speechMode: true })).toBe("Processing…");
    expect(
      isIvrSpeakControlEnabled({ speechMode: true, hasToken: true, busy: true }),
    ).toBe(false);
    expect(
      isIvrSpeakControlEnabled({
        speechMode: isIvrFreeFormSpeechStep(ivrInputMode("AUTHENTICATE", "register_offer")),
        hasToken: true,
        busy: false,
      }),
    ).toBe(false);
  });

  it("auto-enters Listening for register_name and does not submit empty speech", () => {
    expect(ivrInputMode("AUTHENTICATE", "register_name")).toBe("none");
    expect(isIvrFreeFormSpeechStep("none")).toBe(true);
    expect(
      shouldAutoEnterIvrListening({ inCall: true, speechMode: true, busy: false }),
    ).toBe(true);
    expect(
      shouldAutoEnterIvrListening({ inCall: true, speechMode: true, busy: true }),
    ).toBe(false);
    expect(ivrSpeechListeningLabel(true, false)).toBe("Listening…");
    expect(ivrSpeechListeningLabel(false, true)).toBe("Processing…");
    expect(ivrCallPhase({ inCall: true, busy: false, mode: "none" })).toBe("waiting_speech");
    expect(ivrCallPhaseLabel("waiting_speech")).toBe("Listening…");
    // Empty → no voice payload path; only non-empty builds the channel payload.
    expect(canSubmitIvrSpeech("")).toBe(false);
    expect(canSubmitIvrSpeech("   ")).toBe(false);
    expect(ivrVoicePayload("Gautam Prakash")).toEqual({
      modality: "voice",
      transcript: "Gautam Prakash",
    });
    // Helper retained for tests only — UI must not auto-send this.
    expect(ivrNoSpeechPayload()).toEqual({ modality: "voice", transcript: " " });
  });

  it("returns to Listening after a no-speech style reply (still free-form)", () => {
    // Backend no_speech keeps auth_step register_name → UI re-enters speech mode.
    const step = resolveIvrAuthStep("AUTHENTICATE", "register_name");
    const mode = ivrInputMode("AUTHENTICATE", step);
    expect(isIvrFreeFormSpeechStep(mode)).toBe(true);
    expect(
      shouldAutoEnterIvrListening({ inCall: true, speechMode: true, busy: false }),
    ).toBe(true);
    expect(ivrSpeakButtonLabel({ busy: false, speechMode: true })).toBe("Speak");
    // Second attempt uses a fresh transcript (no stale empty submit).
    expect(canSubmitIvrSpeech("Gautam Prakash")).toBe(true);
    expect(ivrVoicePayload("Gautam Prakash").transcript).toBe("Gautam Prakash");
  });

  it("maps physical laptop keys to the same DTMF keypad digits", () => {
    expect(physicalKeyToIvrKey("1")).toBe("1");
    expect(physicalKeyToIvrKey("0")).toBe("0");
    expect(physicalKeyToIvrKey("*")).toBe("*");
    expect(physicalKeyToIvrKey("#")).toBe("#");
    expect(physicalKeyToIvrKey("a")).toBeNull();
    expect(physicalKeyToIvrKey("Enter")).toBeNull();

    // Language / registration / OTP buffering via the shared append path.
    expect(appendIvrKey("", physicalKeyToIvrKey("1")!, "language")).toBe("1");
    expect(shouldAutoSubmitDtmf("language", "1")).toBe(true);
    expect(shouldAutoSubmitDtmf("register", "2")).toBe(true);

    let mobile = "";
    for (const d of "8888888888") {
      mobile = appendIvrKey(mobile, physicalKeyToIvrKey(d)!, "mobile");
    }
    expect(mobile).toBe("8888888888");
    expect(shouldAutoSubmitDtmf("mobile", mobile)).toBe(true);

    let otp = "";
    for (const d of "123456") {
      otp = appendIvrKey(otp, physicalKeyToIvrKey(d)!, "otp");
    }
    expect(otp).toBe("123456");
    expect(shouldAutoSubmitDtmf("otp", otp)).toBe(true);
  });

  it("ignores physical DTMF while typing in speech fields or when speech mode is active", () => {
    expect(
      shouldAcceptIvrPhysicalKey({
        inCall: true,
        keypadMode: true,
        speechMode: false,
      }),
    ).toBe(true);
    expect(
      shouldAcceptIvrPhysicalKey({
        inCall: true,
        keypadMode: false,
        speechMode: true,
      }),
    ).toBe(false);
    expect(
      shouldAcceptIvrPhysicalKey({
        inCall: true,
        keypadMode: true,
        speechMode: true,
      }),
    ).toBe(false);

    const input = {
      tagName: "INPUT",
      isContentEditable: false,
      closest: () => null,
    } as unknown as HTMLElement;
    const div = {
      tagName: "DIV",
      isContentEditable: false,
      closest: () => null,
    } as unknown as HTMLElement;
    expect(shouldIgnoreIvrPhysicalKey(input)).toBe(true);
    expect(shouldIgnoreIvrPhysicalKey(div)).toBe(false);
    expect(shouldIgnoreIvrPhysicalKey(null)).toBe(false);
  });

  it("maps journey auth_step to the correct IVR mode after mobile submit", () => {
    // Existing account → OTP keypad
    expect(ivrModeFromJourney("AUTHENTICATE", "otp")).toBe("otp");
    // Valid unknown mobile → registration offer (not stuck on mobile)
    expect(ivrModeFromJourney("AUTHENTICATE", "register_offer")).toBe("register");
    expect(isIvrKeypadDrivenStep("register")).toBe(true);
    // Invalid mobile / retry → mobile keypad again
    expect(ivrModeFromJourney("AUTHENTICATE", "mobile")).toBe("mobile");
    expect(ivrModeFromJourney("AUTHENTICATE", "")).toBe("mobile");
  });

  it("registration offer 1 stays OTP-bound and 2 returns to mobile via auth_step", () => {
    // Frontend mode after backend maps 1→REGISTER / 2→ANOTHER (journey auth_step).
    expect(ivrModeFromJourney("AUTHENTICATE", "otp")).toBe("otp");
    expect(ivrModeFromJourney("AUTHENTICATE", "mobile")).toBe("mobile");
    expect(appendIvrKey("", "1", "register")).toBe("1");
    expect(appendIvrKey("", "2", "register")).toBe("2");
    expect(shouldAutoSubmitDtmf("register", "1")).toBe(true);
    expect(shouldAutoSubmitDtmf("register", "2")).toBe(true);
  });

  it("locks DTMF while a 10-digit mobile submit is in flight", () => {
    expect(isDtmfSubmitLocked(true, false)).toBe(true);
    expect(isDtmfSubmitLocked(false, true)).toBe(true);
    expect(isDtmfSubmitLocked(false, false)).toBe(false);
    // Rapid extra digits while locked must not grow/submit a second payload.
    expect(
      shouldAcceptIvrPhysicalKey({
        inCall: true,
        keypadMode: true,
        speechMode: false,
        busy: isDtmfSubmitLocked(true, false),
      }),
    ).toBe(false);
  });

  it("submits mobile exactly once at 10 digits and rejects an 11th digit", () => {
    let buf = "";
    let submits = 0;
    for (const d of "98765432101") {
      if (isDtmfSubmitLocked(submits > 0)) break;
      const next = appendIvrKey(buf, d, "mobile");
      if (next === buf) continue;
      buf = next;
      if (shouldAutoSubmitDtmf("mobile", buf)) {
        submits += 1;
        buf = ""; // sendDtmf clears buffer on submit start
      }
    }
    expect(submits).toBe(1);
    expect(buf).toBe("");
    expect(appendIvrKey("9876543210", "1", "mobile")).toBe("9876543210");
  });

  it("resets buffer after invalid or successful mobile submission", () => {
    // After response (invalid or known/unknown), UI clears to empty for a fresh entry.
    expect(formatIvrDisplay("")).toBe("—");
    expect(appendIvrKey("", "9", "mobile")).toBe("9");
    // Stale auth_step must not keep register mode when journey says mobile again.
    expect(ivrModeFromJourney("AUTHENTICATE", "mobile")).toBe("mobile");
    expect(ivrModeFromJourney("AUTHENTICATE", "register_offer")).toBe("register");
  });

  it("physical and on-screen keypad share the same DTMF append/submit path", () => {
    const fromScreen = appendIvrKey("", "9", "mobile");
    const fromPhysical = appendIvrKey("", physicalKeyToIvrKey("9")!, "mobile");
    expect(fromScreen).toBe(fromPhysical);
    expect(ivrDtmfPayload("9876543210")).toEqual({
      modality: "dtmf",
      dtmf: "9876543210",
    });
  });

  it("keeps DTMF for language, mobile, OTP, and registration offer", () => {
    expect(isIvrKeypadDrivenStep(ivrInputMode("LANGUAGE_SELECT"))).toBe(true);
    expect(isIvrKeypadDrivenStep(ivrInputMode("AUTHENTICATE", "mobile"))).toBe(true);
    expect(isIvrKeypadDrivenStep(ivrInputMode("AUTHENTICATE", "otp"))).toBe(true);
    expect(isIvrKeypadDrivenStep(ivrInputMode("AUTHENTICATE", "register_offer"))).toBe(
      true,
    );
    expect(ivrDtmfPayload("1")).toEqual({ modality: "dtmf", dtmf: "1" });
    expect(ivrDtmfPayload("7412589632")).toEqual({
      modality: "dtmf",
      dtmf: "7412589632",
    });
    expect(ivrDtmfPayload("660813")).toEqual({ modality: "dtmf", dtmf: "660813" });
  });

  it("rejects star/hash on language and mobile steps", () => {
    expect(acceptsIvrKey("language", "*")).toBe(false);
    expect(acceptsIvrKey("mobile", "#")).toBe(false);
    expect(acceptsIvrKey("otp", "*")).toBe(false);
  });
});

describe("IVR keypad barges in on active TTS", () => {
  it("stops playing prompt audio when interruptForRecording is used on keypad press", () => {
    const created: Array<PlayableAudio & { paused: boolean; src: string }> = [];
    const session = new ServiceAudioSession({
      createAudio: () => {
        const el = {
          paused: true,
          src: "data:audio/wav;base64,PROMPT",
          currentTime: 3,
          volume: 1,
          onended: null as PlayableAudio["onended"],
          onerror: null as PlayableAudio["onerror"],
          pause() {
            this.paused = true;
          },
          play() {
            this.paused = false;
            return Promise.resolve();
          },
          load() {
            /* noop */
          },
          removeAttribute(name: string) {
            if (name === "src") this.src = "";
          },
        };
        created.push(el);
        return el;
      },
    });

    session.play("PROMPT", "audio/wav");
    expect(session.isPlaying()).toBe(true);

    // Same call path IVR onKey uses before buffering DTMF.
    session.interruptForRecording();

    expect(session.isPlaying()).toBe(false);
    expect(created[0].paused).toBe(true);
    expect(created[0].src).toBe("");
  });

  it("stops playing prompt audio when speech starts (interruptForRecording)", () => {
    const created: Array<PlayableAudio & { paused: boolean; src: string }> = [];
    const session = new ServiceAudioSession({
      createAudio: () => {
        const el = {
          paused: true,
          src: "data:audio/wav;base64,PROMPT",
          currentTime: 2,
          volume: 1,
          onended: null as PlayableAudio["onended"],
          onerror: null as PlayableAudio["onerror"],
          pause() {
            this.paused = true;
          },
          play() {
            this.paused = false;
            return Promise.resolve();
          },
          load() {
            /* noop */
          },
          removeAttribute(name: string) {
            if (name === "src") this.src = "";
          },
        };
        created.push(el);
        return el;
      },
    });
    session.play("PROMPT", "audio/wav");
    expect(session.isPlaying()).toBe(true);
    session.interruptForRecording();
    expect(session.isPlaying()).toBe(false);
    expect(created[0].src).toBe("");
  });
});
