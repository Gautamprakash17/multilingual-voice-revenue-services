import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  lookupSessionHandoff,
  peekLatestHandoff,
  resolveResumeToken,
  storeSessionHandoff,
} from "./sessionHandoff";

function mockSessionStorage() {
  const store = new Map<string, string>();
  const api = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
    get length() {
      return store.size;
    },
    key: (index: number) => Array.from(store.keys())[index] ?? null,
  };
  Object.defineProperty(globalThis, "sessionStorage", {
    value: api,
    configurable: true,
  });
}

beforeEach(() => {
  mockSessionStorage();
});

afterEach(() => {
  sessionStorage.clear();
});

describe("sessionHandoff", () => {
  it("stores and looks up token by application id", () => {
    storeSessionHandoff("INC-1001", "tok-abc");
    expect(lookupSessionHandoff("INC-1001")).toBe("tok-abc");
    expect(peekLatestHandoff()?.applicationId).toBe("INC-1001");
  });

  it("looks up handoff case-insensitively by Application ID", () => {
    storeSessionHandoff("inc-1001", "tok-abc");
    expect(lookupSessionHandoff("INC-1001")).toBe("tok-abc");
    expect(lookupSessionHandoff(" inc-1001 ")).toBe("tok-abc");
  });

  it("returns null when application id is unknown", () => {
    storeSessionHandoff("INC-1001", "tok-abc");
    expect(lookupSessionHandoff("INC-9999")).toBeNull();
  });

  it("prefers a navigation token and stores it for later lookup", () => {
    expect(resolveResumeToken("INC-2002", "tok-nav")).toBe("tok-nav");
    expect(lookupSessionHandoff("INC-2002")).toBe("tok-nav");
  });

  it("falls back to stored handoff when navigation has no token", () => {
    storeSessionHandoff("INC-2003", "tok-stored");
    expect(resolveResumeToken("INC-2003")).toBe("tok-stored");
    expect(resolveResumeToken("INC-2003", "")).toBe("tok-stored");
  });
});
