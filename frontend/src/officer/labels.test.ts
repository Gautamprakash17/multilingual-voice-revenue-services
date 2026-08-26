import { describe, expect, it } from "vitest";
import {
  formatOfficerActionAt,
  formatOfficerChannel,
  isOfficerHistoryMode,
  officerApplicantSummary,
  officerHistoryEmptyMessage,
  officerQueueEmptyMessage,
  officerStatusCounts,
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
    expect(officerQueueEmptyMessage(0, false)).toBe("No applications yet.");
    expect(officerQueueEmptyMessage(0, true)).toBe("Loading applications…");
  });

  it("formats action timestamps for display", () => {
    const formatted = formatOfficerActionAt("2026-08-23T17:44:10.579792+00:00");
    expect(formatted).not.toBe("—");
    expect(formatted.toLowerCase()).toMatch(/aug|08|2026/);
  });

  it("labels channel metadata without affecting queue membership", () => {
    expect(formatOfficerChannel("whatsapp")).toBe("WhatsApp");
    expect(formatOfficerChannel("ivr")).toBe("IVR");
    expect(formatOfficerChannel("web")).toBe("Web");
    expect(formatOfficerChannel(null)).toBe("—");
  });
});

describe("officer summary cards", () => {
  it("counts statuses from existing queue and history payloads", () => {
    const counts = officerStatusCounts(
      [
        { processing_status: "DRAFT" },
        { processing_status: "SUBMITTED" },
        { processing_status: "UNDER_REVIEW" },
        { processing_status: "UNDER_REVIEW" },
        { processing_status: "NEEDS_CORRECTION" },
      ],
      [{ processing_status: "ISSUED" }, { processing_status: "REJECTED" }],
    );
    expect(counts).toEqual({
      inProgress: 1,
      pending: 1,
      underReview: 2,
      needsCorrection: 1,
      issued: 1,
      rejected: 1,
    });
  });

  it("summarizes applicant presence without exposing field values", () => {
    expect(officerApplicantSummary(["applicant_name", "district"])).toBe("On file");
    expect(officerApplicantSummary(["district"])).toBe("Partial");
    expect(officerApplicantSummary([])).toBe("—");
  });
});
