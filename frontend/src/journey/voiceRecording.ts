/**
 * Shared browser microphone capture + WAV encoding for local STT.
 * Extracted from JourneyPage so IVR can reuse the same MediaRecorder → 16 kHz WAV path.
 */

export const WHISPER_SAMPLE_RATE = 16000;

export type MicCaptureOptions = {
  /** RMS above this counts as speech (0–1 scale). */
  speechThreshold?: number;
  /** Require this much speech before silence can end the clip. */
  minSpeechMs?: number;
  /** End capture after this much continuous silence (post-speech). */
  silenceMs?: number;
  /** Hard cap on recording length. */
  maxMs?: number;
  /** Ignore silence detection for this long after start (lets TTS barge-in settle). */
  prerollMs?: number;
  onSpeechStart?: () => void;
};

export type MicCaptureResult = {
  blob: Blob;
  /** True when analyser saw energy above the speech threshold. */
  heardSpeech: boolean;
  durationMs: number;
};

export type MicCaptureHandle = {
  stop: () => void;
  stream: MediaStream;
};

const DEFAULTS: Required<
  Pick<MicCaptureOptions, "speechThreshold" | "minSpeechMs" | "silenceMs" | "maxMs" | "prerollMs">
> = {
  speechThreshold: 0.015,
  minSpeechMs: 350,
  silenceMs: 1100,
  maxMs: 8000,
  prerollMs: 250,
};

export function blobToBase64(blob: Blob): Promise<string> {
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

function writeAscii(view: DataView, offset: number, text: string) {
  for (let i = 0; i < text.length; i++) {
    view.setUint8(offset + i, text.charCodeAt(i));
  }
}

export function encodeWavPcm16(samples: Float32Array, sampleRate: number): Blob {
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
export async function recordingBlobToWavBase64(blob: Blob): Promise<string> {
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

export function preferredRecorderMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) return "audio/webm;codecs=opus";
  if (MediaRecorder.isTypeSupported("audio/webm")) return "audio/webm";
  return undefined;
}

export function isBrowserMicSupported(): boolean {
  return (
    typeof navigator !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia) &&
    typeof MediaRecorder !== "undefined"
  );
}

export function isMicPermissionDeniedError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const name = "name" in err ? String((err as { name?: string }).name) : "";
  return (
    name === "NotAllowedError" ||
    name === "PermissionDeniedError" ||
    name === "SecurityError"
  );
}

/**
 * Decide auto-stop given current RMS sample.
 * Returns updated bookkeeping plus whether to stop now.
 */
export function tickMicSilenceDetector(
  prev: {
    heardSpeech: boolean;
    speechMs: number;
    lastLoudAt: number | null;
  },
  opts: {
    now: number;
    startedAt: number;
    rms: number;
    speechThreshold: number;
    prerollMs: number;
    minSpeechMs: number;
    silenceMs: number;
    maxMs: number;
  },
): { heardSpeech: boolean; speechMs: number; lastLoudAt: number | null; stop: boolean } {
  const elapsed = opts.now - opts.startedAt;
  let { heardSpeech, speechMs, lastLoudAt } = prev;
  const loud = opts.rms >= opts.speechThreshold;
  if (loud) {
    if (!heardSpeech) heardSpeech = true;
    lastLoudAt = opts.now;
    speechMs += 50; // callers typically tick ~50ms
  }
  if (elapsed >= opts.maxMs) {
    return { heardSpeech, speechMs, lastLoudAt, stop: true };
  }
  if (elapsed < opts.prerollMs) {
    return { heardSpeech, speechMs, lastLoudAt, stop: false };
  }
  if (
    heardSpeech &&
    speechMs >= opts.minSpeechMs &&
    lastLoudAt != null &&
    opts.now - lastLoudAt >= opts.silenceMs
  ) {
    return { heardSpeech, speechMs, lastLoudAt, stop: true };
  }
  return { heardSpeech, speechMs, lastLoudAt, stop: false };
}

function rmsFromAnalyser(analyser: AnalyserNode, buf: Uint8Array): number {
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = (buf[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / buf.length);
}

/**
 * Open the mic, record until silence / max duration, then resolve with a WebM/WAV-ready blob.
 * Caller should convert with {@link recordingBlobToWavBase64} before sending to the channel API.
 */
export async function captureMicUtterance(
  options: MicCaptureOptions = {},
): Promise<{ handle: MicCaptureHandle; done: Promise<MicCaptureResult> }> {
  if (!isBrowserMicSupported()) {
    throw new Error("Microphone capture is not supported in this browser.");
  }
  const cfg = { ...DEFAULTS, ...options };
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mime = preferredRecorderMimeType();
  const recorder = mime
    ? new MediaRecorder(stream, { mimeType: mime })
    : new MediaRecorder(stream);
  const chunks: Blob[] = [];
  const startedAt = performance.now();
  let heardSpeech = false;
  let speechMs = 0;
  let lastLoudAt: number | null = null;
  let settled = false;
  let audioCtx: AudioContext | null = null;
  const raf = 0;
  let tickTimer = 0;

  const cleanupGraph = () => {
    if (raf) cancelAnimationFrame(raf);
    if (tickTimer) window.clearInterval(tickTimer);
    if (audioCtx) {
      void audioCtx.close();
      audioCtx = null;
    }
  };

  const stopTracks = () => {
    stream.getTracks().forEach((t) => t.stop());
  };

  recorder.ondataavailable = (e) => {
    if (e.data.size) chunks.push(e.data);
  };

  const done = new Promise<MicCaptureResult>((resolve, reject) => {
    recorder.onerror = () => {
      if (settled) return;
      settled = true;
      cleanupGraph();
      stopTracks();
      reject(new Error("Microphone recording failed."));
    };
    recorder.onstop = () => {
      if (settled) return;
      settled = true;
      cleanupGraph();
      stopTracks();
      const mimeType = recorder.mimeType || mime || "audio/webm";
      const blob = new Blob(chunks, { type: mimeType });
      resolve({
        blob,
        heardSpeech,
        durationMs: Math.round(performance.now() - startedAt),
      });
    };
  });

  try {
    audioCtx = new AudioContext();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    const buf = new Uint8Array(analyser.fftSize);

    const tick = () => {
      if (settled || recorder.state !== "recording") return;
      const now = performance.now();
      const rms = rmsFromAnalyser(analyser, buf);
      const next = tickMicSilenceDetector(
        { heardSpeech, speechMs, lastLoudAt },
        {
          now,
          startedAt,
          rms,
          speechThreshold: cfg.speechThreshold,
          prerollMs: cfg.prerollMs,
          minSpeechMs: cfg.minSpeechMs,
          silenceMs: cfg.silenceMs,
          maxMs: cfg.maxMs,
        },
      );
      if (next.heardSpeech && !heardSpeech) {
        options.onSpeechStart?.();
      }
      heardSpeech = next.heardSpeech;
      speechMs = next.speechMs;
      lastLoudAt = next.lastLoudAt;
      if (next.stop && recorder.state === "recording") {
        recorder.stop();
        return;
      }
    };

    tickTimer = window.setInterval(tick, 50);
    recorder.start(200);
  } catch (err) {
    cleanupGraph();
    stopTracks();
    throw err;
  }

  const handle: MicCaptureHandle = {
    stream,
    stop: () => {
      if (recorder.state === "recording") recorder.stop();
      else {
        cleanupGraph();
        stopTracks();
      }
    },
  };

  return { handle, done };
}

/** True when a captured blob is large enough to bother sending to STT. */
export function isUsableRecordingBlob(blob: Blob, heardSpeech: boolean): boolean {
  return heardSpeech && blob.size >= 32;
}

export const IVR_MIC_DENIED_MESSAGE =
  "Microphone access is required for voice input. You can use the developer fallback for this simulator.";

export const IVR_MIC_SILENCE_MESSAGE =
  "I couldn't understand you. Please speak clearly.";
