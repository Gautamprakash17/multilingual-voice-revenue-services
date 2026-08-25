/** Presentation helpers for the local synthetic OTP phone simulator. */

export const SYNTHETIC_OTP_LABEL = "Synthetic demo OTP";

export function formatOtpForDisplay(code: string): string {
  const digits = (code || "").replace(/\D/g, "");
  if (digits.length === 6) {
    return `${digits.slice(0, 3)} ${digits.slice(3)}`;
  }
  return digits;
}

export function authStepFromReply(data: Record<string, unknown> | null | undefined): string {
  const step = data?.auth_step;
  return typeof step === "string" ? step : "";
}

export function otpIssuedFromReply(data: Record<string, unknown> | null | undefined): boolean {
  return data?.otp_issued === true;
}

export function shouldShowPhoneSimulator(opts: {
  state?: string | null;
  authStep?: string | null;
  otpIssued?: boolean;
}): boolean {
  return opts.state === "AUTHENTICATE" && opts.authStep === "otp" && Boolean(opts.otpIssued);
}

export function isExistingCitizenLogin(opts: {
  state?: string | null;
  authStep?: string | null;
  citizenKind?: string | null;
}): boolean {
  return (
    opts.state === "AUTHENTICATE" &&
    opts.authStep === "otp" &&
    opts.citizenKind !== "new"
  );
}

export function isNewCitizenRegistration(opts: {
  state?: string | null;
  authStep?: string | null;
}): boolean {
  return (
    opts.state === "AUTHENTICATE" &&
    (opts.authStep === "register_offer" || opts.authStep === "register_name")
  );
}

export function otpErrorCopy(error: string | null | undefined): string | null {
  if (error === "invalid_otp") {
    return "That OTP is incorrect. Please try again.";
  }
  if (error === "otp_expired") {
    return "That OTP has expired. A new code has been sent.";
  }
  return null;
}
