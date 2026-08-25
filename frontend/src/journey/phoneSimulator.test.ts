import { describe, expect, it } from "vitest";
import {
  SYNTHETIC_OTP_LABEL,
  authStepFromReply,
  formatOtpForDisplay,
  isExistingCitizenLogin,
  isNewCitizenRegistration,
  otpIssuedFromReply,
  shouldShowPhoneSimulator,
  otpErrorCopy,
} from "./phoneSimulator";

describe("phone simulator visibility", () => {
  it("is hidden before OTP is issued", () => {
    expect(
      shouldShowPhoneSimulator({
        state: "AUTHENTICATE",
        authStep: "mobile",
        otpIssued: false,
      }),
    ).toBe(false);
    expect(
      shouldShowPhoneSimulator({
        state: "LANGUAGE_SELECT",
        authStep: "",
        otpIssued: false,
      }),
    ).toBe(false);
  });

  it("appears after OTP issuance during authenticate", () => {
    expect(
      shouldShowPhoneSimulator({
        state: "AUTHENTICATE",
        authStep: "otp",
        otpIssued: true,
      }),
    ).toBe(true);
  });

  it("hides after successful authentication", () => {
    expect(
      shouldShowPhoneSimulator({
        state: "CONSENT",
        authStep: "complete",
        otpIssued: false,
      }),
    ).toBe(false);
    expect(
      shouldShowPhoneSimulator({
        state: "AUTHENTICATE",
        authStep: "register_name",
        otpIssued: false,
      }),
    ).toBe(false);
  });
});

describe("OTP display", () => {
  it("spaces six digits for readability", () => {
    expect(formatOtpForDisplay("583214")).toBe("583 214");
    expect(formatOtpForDisplay("041927")).toBe("041 927");
  });

  it("shows the synthetic demo label", () => {
    expect(SYNTHETIC_OTP_LABEL).toBe("Synthetic demo OTP");
  });
});

describe("login vs registration UI flags", () => {
  it("marks existing citizen OTP login", () => {
    expect(
      isExistingCitizenLogin({
        state: "AUTHENTICATE",
        authStep: "otp",
        citizenKind: "existing",
      }),
    ).toBe(true);
  });

  it("marks new citizen registration steps", () => {
    expect(
      isNewCitizenRegistration({
        state: "AUTHENTICATE",
        authStep: "register_offer",
      }),
    ).toBe(true);
    expect(
      isNewCitizenRegistration({
        state: "AUTHENTICATE",
        authStep: "register_name",
      }),
    ).toBe(true);
  });

  it("reads auth flags from journey data", () => {
    expect(authStepFromReply({ auth_step: "otp", otp_issued: true })).toBe("otp");
    expect(otpIssuedFromReply({ otp_issued: true })).toBe(true);
  });
});

describe("wrong / expired OTP remain authenticate OTP step", () => {
  it("keeps the simulator visible while retrying a wrong OTP", () => {
    expect(
      shouldShowPhoneSimulator({
        state: "AUTHENTICATE",
        authStep: "otp",
        otpIssued: true,
      }),
    ).toBe(true);
    expect(otpErrorCopy("invalid_otp")).toBe("That OTP is incorrect. Please try again.");
  });

  it("keeps the simulator visible after an expired OTP is replaced", () => {
    expect(
      shouldShowPhoneSimulator({
        state: "AUTHENTICATE",
        authStep: "otp",
        otpIssued: true,
      }),
    ).toBe(true);
    expect(otpErrorCopy("otp_expired")).toBe(
      "That OTP has expired. A new code has been sent.",
    );
  });
});
