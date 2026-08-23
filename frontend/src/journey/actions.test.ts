import { describe, expect, it } from "vitest";
import {
  acceptsCitizenComposer,
  isTerminalJourneyState,
  showsFieldConfirmationActions,
  showsPaymentActions,
} from "./actions";

describe("journey UI state capabilities", () => {
  it("shows composer for active conversational states", () => {
    expect(acceptsCitizenComposer("LANGUAGE_SELECT")).toBe(true);
    expect(acceptsCitizenComposer("FORM_CAPTURE")).toBe(true);
    expect(acceptsCitizenComposer("FIELD_CONFIRMATION")).toBe(true);
    expect(acceptsCitizenComposer("REVIEW_CONFIRM")).toBe(true);
    expect(acceptsCitizenComposer("AUTHENTICATE")).toBe(true);
  });

  it("keeps composer available in payment states so voice can complete the journey", () => {
    expect(acceptsCitizenComposer("FEE_QUOTE")).toBe(true);
    expect(acceptsCitizenComposer("PAYMENT")).toBe(true);
    expect(acceptsCitizenComposer("PAYMENT_FAILED")).toBe(true);
  });

  it("hides composer for terminal states", () => {
    expect(acceptsCitizenComposer("SUBMITTED")).toBe(false);
    expect(acceptsCitizenComposer("ESCALATED")).toBe(false);
    expect(acceptsCitizenComposer(null)).toBe(false);
  });

  it("keeps payment buttons alongside the composer in payment states", () => {
    for (const state of ["FEE_QUOTE", "PAYMENT", "PAYMENT_FAILED"]) {
      expect(acceptsCitizenComposer(state)).toBe(true);
      expect(showsPaymentActions(state)).toBe(true);
    }
  });

  it("shows payment actions only in fee/payment states", () => {
    expect(showsPaymentActions("FEE_QUOTE")).toBe(true);
    expect(showsPaymentActions("PAYMENT")).toBe(true);
    expect(showsPaymentActions("PAYMENT_FAILED")).toBe(true);
    expect(showsPaymentActions("SUBMITTED")).toBe(false);
    expect(showsPaymentActions("REVIEW_CONFIRM")).toBe(false);
  });

  it("shows field confirmation actions only in confirmation state", () => {
    expect(showsFieldConfirmationActions("FIELD_CONFIRMATION")).toBe(true);
    expect(showsFieldConfirmationActions("FORM_CAPTURE")).toBe(false);
    expect(showsFieldConfirmationActions(null)).toBe(false);
  });

  it("marks submitted and escalated as terminal", () => {
    expect(isTerminalJourneyState("SUBMITTED")).toBe(true);
    expect(isTerminalJourneyState("ESCALATED")).toBe(true);
    expect(isTerminalJourneyState("FORM_CAPTURE")).toBe(false);
  });
});
