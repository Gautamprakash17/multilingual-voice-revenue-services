import { describe, expect, it } from "vitest";
import { citizenVisibleText } from "./chatText";

describe("citizenVisibleText", () => {
  it("shows identical message and prompt only once", () => {
    const text =
      "Please review your application. Say yes to continue to payment, or say change to edit a detail.";
    expect(citizenVisibleText(text, text)).toBe(text);
  });

  it("dedupes fee quote when prompt repeats the trailing instruction", () => {
    const message =
      "The application fee is 50.00 INR. Say yes to pay now, or say change to edit your details.";
    const prompt = "Say yes to pay now, or say change to edit your details.";
    expect(citizenVisibleText(message, prompt)).toBe(message);
  });

  it("dedupes payment confirm when message and prompt match after normalize", () => {
    const text =
      "Please confirm payment of 50.00 INR. Say yes to complete the payment, or say cancel to go back.";
    expect(citizenVisibleText(text, `  ${text}  `)).toBe(text);
  });

  it("keeps distinct welcome + language prompt", () => {
    const message = "Welcome to Revenue Services.";
    const prompt = "Please choose your preferred language: English, हिन्दी, or ಕನ್ನಡ.";
    expect(citizenVisibleText(message, prompt)).toBe(`${message}\n${prompt}`);
  });

  it("drops commandish tester prompts", () => {
    expect(citizenVisibleText("Confirm your details.", "Reply CONFIRM or CORRECT")).toBe(
      "Confirm your details.",
    );
  });

  it("does not invent empty content", () => {
    expect(citizenVisibleText("", "Only prompt")).toBe("Only prompt");
    expect(citizenVisibleText("Only message", null)).toBe("Only message");
  });
});
