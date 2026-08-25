import { describe, expect, it } from "vitest";
import {
  IVR_MIC_DENIED_MESSAGE,
  IVR_MIC_SILENCE_MESSAGE,
  isMicPermissionDeniedError,
  isUsableRecordingBlob,
  tickMicSilenceDetector,
} from "./voiceRecording";
import {
  ivrAudioVoicePayload,
  ivrVoicePayload,
  mergeIvrAuthStep,
  shouldAutoEnterIvrListening,
  ivrSpeechListeningLabel,
  ivrInputMode,
  isIvrFreeFormSpeechStep,
  canSubmitIvrSpeech,
} from "./ivrDtmf";

describe("IVR microphone capture helpers", () => {
  it("auto-enters listening for register_name speech mode", () => {
    const mode = ivrInputMode("AUTHENTICATE", "register_name");
    expect(isIvrFreeFormSpeechStep(mode)).toBe(true);
    expect(
      shouldAutoEnterIvrListening({ inCall: true, speechMode: true, busy: false }),
    ).toBe(true);
    expect(ivrSpeechListeningLabel(true, false, { micActive: true })).toBe("Listening…");
  });

  it("builds audio voice payload without a client transcript (backend STT)", () => {
    expect(ivrAudioVoicePayload("abc123")).toEqual({
      modality: "voice",
      audio_b64: "abc123",
    });
    expect(ivrVoicePayload("Gautam Prakash")).toEqual({
      modality: "voice",
      transcript: "Gautam Prakash",
    });
    expect(canSubmitIvrSpeech("")).toBe(false);
  });

  it("does not treat empty/silent blobs as usable recordings", () => {
    expect(isUsableRecordingBlob(new Blob(["x"]), false)).toBe(false);
    expect(isUsableRecordingBlob(new Blob([]), true)).toBe(false);
    expect(isUsableRecordingBlob(new Blob(["0123456789".repeat(4)]), true)).toBe(true);
  });

  it("stops after speech followed by silence, not before speech", () => {
    const startedAt = 0;
    let state = { heardSpeech: false, speechMs: 0, lastLoudAt: null as number | null };
    // Quiet preroll
    state = tickMicSilenceDetector(state, {
      now: 300,
      startedAt,
      rms: 0.001,
      speechThreshold: 0.015,
      prerollMs: 250,
      minSpeechMs: 350,
      silenceMs: 1100,
      maxMs: 8000,
    });
    expect(state.stop).toBe(false);

    // Speech
    for (let t = 400; t <= 900; t += 50) {
      state = tickMicSilenceDetector(state, {
        now: t,
        startedAt,
        rms: 0.05,
        speechThreshold: 0.015,
        prerollMs: 250,
        minSpeechMs: 350,
        silenceMs: 1100,
        maxMs: 8000,
      });
    }
    expect(state.heardSpeech).toBe(true);
    expect(state.stop).toBe(false);

    // Silence after speech
    state = tickMicSilenceDetector(state, {
      now: 2100,
      startedAt,
      rms: 0.001,
      speechThreshold: 0.015,
      prerollMs: 250,
      minSpeechMs: 350,
      silenceMs: 1100,
      maxMs: 8000,
    });
    expect(state.stop).toBe(true);
  });

  it("stops at max duration even without speech", () => {
    const state = tickMicSilenceDetector(
      { heardSpeech: false, speechMs: 0, lastLoudAt: null },
      {
        now: 8000,
        startedAt: 0,
        rms: 0,
        speechThreshold: 0.015,
        prerollMs: 250,
        minSpeechMs: 350,
        silenceMs: 1100,
        maxMs: 8000,
      },
    );
    expect(state.stop).toBe(true);
    expect(state.heardSpeech).toBe(false);
  });

  it("preserves auth_step when STT unrecognized omits it", () => {
    expect(mergeIvrAuthStep("AUTHENTICATE", "", "register_name")).toBe("register_name");
    expect(mergeIvrAuthStep("AUTHENTICATE", "otp", "register_name")).toBe("otp");
    expect(mergeIvrAuthStep("CONSENT", "", "register_name")).toBe("");
  });

  it("detects mic permission denial errors", () => {
    expect(isMicPermissionDeniedError({ name: "NotAllowedError" })).toBe(true);
    expect(isMicPermissionDeniedError({ name: "TypeError" })).toBe(false);
    expect(IVR_MIC_DENIED_MESSAGE).toMatch(/Microphone access/i);
    expect(IVR_MIC_SILENCE_MESSAGE).toMatch(/speak clearly/i);
  });
});
