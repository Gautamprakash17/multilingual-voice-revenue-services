import { describe, expect, it } from "vitest";
import {
  citizenSeesSessionToken,
  ivrDocumentContinueCopy,
  missingSameBrowserHandoffMessage,
  whatsappContinueHint,
} from "./applicationIdentity";

describe("application identity copy", () => {
  it("IVR document continue uses Application ID and never a session token", () => {
    const copy = ivrDocumentContinueCopy("INC-1234");
    expect(copy).toContain("INC-1234");
    expect(copy).toMatch(/WhatsApp/i);
    expect(citizenSeesSessionToken(copy)).toBe(false);
  });

  it("WhatsApp continue asks only for Application ID", () => {
    const hint = whatsappContinueHint();
    expect(hint).toMatch(/Application ID/i);
    expect(citizenSeesSessionToken(hint)).toBe(false);
    expect(citizenSeesSessionToken(missingSameBrowserHandoffMessage())).toBe(false);
  });
});
