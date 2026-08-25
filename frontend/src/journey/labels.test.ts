import { describe, expect, it } from "vitest";
import {
  citizenServiceBlurb,
  fieldLabel,
  processingStatusBadgeClass,
  processingStatusLabel,
  statusLifecycleSteps,
} from "./labels";

describe("citizen presentation labels", () => {
  it("uses human field names instead of internal keys", () => {
    expect(fieldLabel("applicant_name")).toBe("Full name");
    expect(fieldLabel("annual_income")).toBe("Annual income (INR)");
  });

  it("maps processing statuses to citizen-friendly copy", () => {
    expect(processingStatusLabel("SUBMITTED")).toBe("Submitted");
    expect(processingStatusLabel("UNDER_REVIEW")).toBe("Under review");
    expect(processingStatusLabel("NEEDS_CORRECTION")).toBe("Correction required");
    expect(processingStatusLabel("ISSUED")).toBe("Issued");
    expect(processingStatusLabel("REJECTED")).toBe("Rejected");
    expect(processingStatusBadgeClass("ISSUED")).toContain("badge-success");
    expect(processingStatusBadgeClass("REJECTED")).toContain("badge-error");
    expect(processingStatusBadgeClass("NEEDS_CORRECTION")).toContain("badge-warning");
  });

  it("strips implementation wording from catalogue blurbs", () => {
    expect(
      citizenServiceBlurb(
        "Apply for an Income Certificate. POC service definition — rules are declarative.",
      ),
    ).not.toMatch(/POC service definition/i);
    expect(citizenServiceBlurb("")).toContain("guided digital journey");
  });

  it("builds a compact status lifecycle from existing statuses", () => {
    const underReview = statusLifecycleSteps("UNDER_REVIEW");
    expect(underReview.map((s) => s.id)).toEqual(["SUBMITTED", "UNDER_REVIEW", "ISSUED"]);
    expect(underReview.find((s) => s.id === "UNDER_REVIEW")?.phase).toBe("current");
    expect(underReview.find((s) => s.id === "SUBMITTED")?.phase).toBe("done");

    const correction = statusLifecycleSteps("NEEDS_CORRECTION");
    expect(correction.map((s) => s.id)).toContain("NEEDS_CORRECTION");
    expect(correction.find((s) => s.id === "NEEDS_CORRECTION")?.phase).toBe("current");

    const issued = statusLifecycleSteps("ISSUED");
    expect(issued.find((s) => s.id === "ISSUED")?.phase).toBe("current");
    expect(statusLifecycleSteps("DRAFT")).toEqual([]);
  });
});
