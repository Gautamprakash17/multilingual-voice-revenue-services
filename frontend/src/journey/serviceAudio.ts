/**
 * Client-side service TTS playback — barge-in and single-player rules.
 * No backend involvement; never auto-restarts after the citizen interrupts.
 */

export type PlayableAudio = {
  pause: () => void;
  play: () => Promise<void>;
  load?: () => void;
  removeAttribute?: (name: string) => void;
  currentTime: number;
  volume: number;
  onended: ((ev?: Event) => void) | null;
  onerror: ((ev?: Event) => void) | null;
};

export type ServiceAudioPayload = { b64: string; mime: string };

export type ServiceAudioUiState = "idle" | "playing" | "blocked";

/** Hard-stop an HTMLAudioElement (or test double). Safe if null / already stopped. */
export function hardStopAudio(audio: PlayableAudio | null | undefined): void {
  if (!audio) return;
  try {
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    audio.currentTime = 0;
    if (typeof audio.removeAttribute === "function") {
      audio.removeAttribute("src");
    }
    if (typeof audio.load === "function") {
      audio.load();
    }
  } catch {
    /* ignore browser audio edge cases */
  }
}

export type ServiceAudioSessionOptions = {
  /** Injected for tests; defaults to browser Audio. */
  createAudio?: (dataUrl: string) => PlayableAudio;
  volume?: number;
};

/**
 * Owns at most one playing service TTS element.
 * Speak/barge-in calls {@link interruptForRecording} before the mic starts.
 */
export class ServiceAudioSession {
  private current: PlayableAudio | null = null;
  private last: ServiceAudioPayload | null = null;
  private uiState: ServiceAudioUiState = "idle";
  private readonly createAudio: (dataUrl: string) => PlayableAudio;
  private readonly volume: number;
  private onUiState?: (state: ServiceAudioUiState) => void;

  constructor(opts: ServiceAudioSessionOptions = {}) {
    this.volume = opts.volume ?? 0.35;
    this.createAudio =
      opts.createAudio ??
      ((dataUrl: string) => {
        const audio = new Audio(dataUrl) as unknown as PlayableAudio;
        audio.volume = this.volume;
        return audio;
      });
  }

  setUiStateListener(listener: ((state: ServiceAudioUiState) => void) | undefined): void {
    this.onUiState = listener;
  }

  getUiState(): ServiceAudioUiState {
    return this.uiState;
  }

  getLastPayload(): ServiceAudioPayload | null {
    return this.last;
  }

  getCurrentElement(): PlayableAudio | null {
    return this.current;
  }

  isPlaying(): boolean {
    return this.uiState === "playing" && this.current != null;
  }

  /**
   * Barge-in: stop service TTS immediately before microphone recording.
   * Keeps the last payload for manual replay; does not auto-restart.
   */
  interruptForRecording(): void {
    this.stopPlayback();
  }

  /** Stop current playback without clearing the last replayable payload. */
  stopPlayback(): void {
    hardStopAudio(this.current);
    this.current = null;
    this.setState("idle");
  }

  /** Stop playback and forget the last payload (e.g. new journey start). */
  clear(): void {
    this.stopPlayback();
    this.last = null;
  }

  /**
   * Play latest service TTS. Always stops any previous element first
   * so responses never overlap.
   */
  play(b64: string, mime?: string | null): void {
    if (!b64) return;
    this.stopPlayback();
    const audioMime = mime || "audio/wav";
    this.last = { b64, mime: audioMime };
    const audio = this.createAudio(`data:${audioMime};base64,${b64}`);
    audio.volume = this.volume;
    this.current = audio;
    this.setState("playing");

    const clearIfCurrent = () => {
      if (this.current === audio) {
        this.current = null;
      }
    };

    audio.onended = () => {
      clearIfCurrent();
      this.setState("idle");
    };
    audio.onerror = () => {
      clearIfCurrent();
      this.setState("blocked");
    };

    void Promise.resolve(audio.play()).catch(() => {
      clearIfCurrent();
      this.setState("blocked");
    });
  }

  /** Manual replay — same as play(last). Never called automatically after barge-in. */
  replay(): void {
    if (!this.last) return;
    this.play(this.last.b64, this.last.mime);
  }

  private setState(state: ServiceAudioUiState): void {
    this.uiState = state;
    this.onUiState?.(state);
  }
}
