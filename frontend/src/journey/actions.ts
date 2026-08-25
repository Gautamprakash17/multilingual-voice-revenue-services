/** Maps citizen-facing UI actions to existing backend journey command tokens. */
export const JOURNEY_COMMANDS = {
  consentYes: "YES",
  consentNo: "NO",
  fieldConfirmYes: "YES",
  fieldConfirmNo: "NO",
  confirm: "CONFIRM",
  correct: "CORRECT",
  pay: "PAY",
  cancel: "CANCEL",
  paymentFail: "FAIL",
  paymentTimeout: "TIMEOUT",
  retry: "RETRY",
  register: "REGISTER",
  anotherNumber: "ANOTHER",
} as const;

export type JourneyCommand = (typeof JOURNEY_COMMANDS)[keyof typeof JOURNEY_COMMANDS];

/** Internal error codes that must not be shown in citizen-facing UI copy. */
export const INTERNAL_UI_ERRORS = new Set([
  "stt_unrecognized",
  "invalid_language",
  "language_ambiguous",
  "unknown_mobile",
  "invalid_otp",
  "otp_expired",
  "otp_max_attempts",
  "reply_CONFIRM_or_CORRECT",
  "reply_PAY_or_CORRECT",
  "unknown_service",
  "consent_required",
]);

/**
 * Journey states where free-text / Speak input is accepted.
 * Payment states keep their action buttons and also accept voice, so a citizen
 * who started by voice can finish by voice. Terminal states accept neither.
 */
export const COMPOSER_ENABLED_STATES = new Set<string>([
  "LANGUAGE_SELECT",
  "AUTHENTICATE",
  "AUTH_FAILED",
  "CONSENT",
  "SERVICE_SELECT",
  "FORM_CAPTURE",
  "FIELD_CONFIRMATION",
  "DOCUMENT_CAPTURE",
  "DOCUMENT_REJECTED",
  "REVIEW_CONFIRM",
  "CORRECTION",
  "FEE_QUOTE",
  "PAYMENT",
  "PAYMENT_FAILED",
]);

/** States where mock payment / fee action buttons are valid. */
export const PAYMENT_ACTION_STATES = new Set<string>([
  "FEE_QUOTE",
  "PAYMENT",
  "PAYMENT_FAILED",
]);

/** Completed / parked states — no citizen message composer. */
export const TERMINAL_JOURNEY_STATES = new Set<string>(["SUBMITTED", "ESCALATED"]);

export function acceptsCitizenComposer(state: string | null | undefined): boolean {
  if (!state) return false;
  return COMPOSER_ENABLED_STATES.has(state);
}

export function showsPaymentActions(state: string | null | undefined): boolean {
  if (!state) return false;
  return PAYMENT_ACTION_STATES.has(state);
}

export function showsFieldConfirmationActions(state: string | null | undefined): boolean {
  if (!state) return false;
  return state === "FIELD_CONFIRMATION";
}

export function isTerminalJourneyState(state: string | null | undefined): boolean {
  if (!state) return false;
  return TERMINAL_JOURNEY_STATES.has(state);
}
