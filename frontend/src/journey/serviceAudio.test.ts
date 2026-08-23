import { describe, expect, it, vi } from "vitest";
import {
  ServiceAudioSession,
  hardStopAudio,
  type PlayableAudio,
} from "./serviceAudio";

function mockAudio(): PlayableAudio & { paused: boolean; src: string; playCalls: number } {
  const el = {
    paused: true,
    src: "data:audio/wav;base64,OLD",
    playCalls: 0,
    currentTime: 12,
    volume: 1,
    onended: null as PlayableAudio["onended"],
    onerror: null as PlayableAudio["onerror"],
    pause() {
      this.paused = true;
    },
    play() {
      this.playCalls += 1;
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
  return el;
}

describe("hardStopAudio", () => {
  it("is a no-op for null", () => {
    expect(() => hardStopAudio(null)).not.toThrow();
  });

  it("pauses, resets, and clears src without throwing", () => {
    const audio = mockAudio();
    audio.paused = false;
    hardStopAudio(audio);
    expect(audio.paused).toBe(true);
    expect(audio.currentTime).toBe(0);
    expect(audio.src).toBe("");
    expect(audio.onended).toBeNull();
    expect(audio.onerror).toBeNull();
  });
});

describe("ServiceAudioSession barge-in and single player", () => {
  it("stops active TTS before recording begins (Speak barge-in)", () => {
    const created: ReturnType<typeof mockAudio>[] = [];
    const session = new ServiceAudioSession({
      createAudio: () => {
        const a = mockAudio();
        created.push(a);
        return a;
      },
    });

    session.play("AAA", "audio/wav");
    expect(session.isPlaying()).toBe(true);
    expect(created[0].paused).toBe(false);

    // Citizen presses Speak — interrupt before mic
    session.interruptForRecording();

    expect(session.isPlaying()).toBe(false);
    expect(created[0].paused).toBe(true);
    expect(created[0].src).toBe("");
    expect(session.getCurrentElement()).toBeNull();
    // Last payload kept for manual replay only — no auto restart
    expect(session.getLastPayload()).toEqual({ b64: "AAA", mime: "audio/wav" });
  });

  it("starts recording path normally when no TTS is playing", () => {
    const session = new ServiceAudioSession({
      createAudio: () => mockAudio(),
    });
    expect(session.isPlaying()).toBe(false);
    expect(() => session.interruptForRecording()).not.toThrow();
    expect(session.isPlaying()).toBe(false);
    expect(session.getCurrentElement()).toBeNull();
  });

  it("stops previous TTS when a newer service response arrives", () => {
    const created: ReturnType<typeof mockAudio>[] = [];
    const session = new ServiceAudioSession({
      createAudio: () => {
        const a = mockAudio();
        created.push(a);
        return a;
      },
    });

    session.play("OLD", "audio/wav");
    const first = created[0];
    expect(first.paused).toBe(false);

    session.play("NEW", "audio/wav");
    expect(first.paused).toBe(true);
    expect(first.src).toBe("");
    expect(created).toHaveLength(2);
    expect(created[1].paused).toBe(false);
    expect(created[1].playCalls).toBe(1);
    expect(session.getLastPayload()?.b64).toBe("NEW");
    expect(session.getCurrentElement()).toBe(created[1]);
  });

  it("does not restart old TTS when recording stops / interrupt ends", () => {
    const created: ReturnType<typeof mockAudio>[] = [];
    const session = new ServiceAudioSession({
      createAudio: () => {
        const a = mockAudio();
        created.push(a);
        return a;
      },
    });

    session.play("PROMPT", "audio/wav");
    session.interruptForRecording();
    // Recording finishes — no automatic replay
    expect(session.isPlaying()).toBe(false);
    expect(created.filter((a) => !a.paused)).toHaveLength(0);
    expect(created[0].playCalls).toBe(1); // only the original play
  });

  it("does not introduce a recording beep (no extra Audio on interrupt)", () => {
    const createAudio = vi.fn(() => mockAudio());
    const session = new ServiceAudioSession({ createAudio });
    session.play("X", "audio/wav");
    createAudio.mockClear();
    session.interruptForRecording();
    expect(createAudio).not.toHaveBeenCalled();
  });

  it("handles play failures without throwing", () => {
    const session = new ServiceAudioSession({
      createAudio: () => {
        const a = mockAudio();
        a.play = () => Promise.reject(new Error("NotAllowedError"));
        return a;
      },
    });
    expect(() => session.play("Z", "audio/wav")).not.toThrow();
  });
});
