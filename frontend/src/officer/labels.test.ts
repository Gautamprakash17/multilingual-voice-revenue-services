import { describe, expect, it } from "vitest";
import {
  formatOfficerActionAt,
  isOfficerHistoryMode,
  officerHistoryEmptyMessage,
  officerQueueEmptyMessage,
} from "./labels";

describe("officer history UI helpers", () => {
  it("distinguishes applications vs history modes", () => {
    expect(isOfficerHistoryMode("history")).toBe(true);
    expect(isOfficerHistoryMode("applications")).toBe(false);
  });

  it("shows empty and loading copy for history", () => {
    expect(officerHistoryEmptyMessage(0, true)).toBe("Loading history…");
    expect(officerHistoryEmptyMessage(0, false)).toBe(
      "No completed officer actions yet.",
    );
    expect(officerHistoryEmptyMessage(2, false)).toBe("");
  });

  it("keeps queue empty copy for applications tab", () => {
    expect(officerQueueEmptyMessage(0, false)).toContain("No applications requiring review");
    expect(officerQueueEmptyMessage(0, true)).toBe("Loading applications…");
  });

  it("formats action timestamps for display", () => {
    const formatted = formatOfficerActionAt("2026-08-23T17:44:10.579792+00:00");
    expect(formatted).not.toBe("—");
    expect(formatted.toLowerCase()).toMatch(/aug|08|2026/);
  });
});
