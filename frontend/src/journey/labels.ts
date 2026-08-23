/** Citizen-facing display labels — presentation only, not business rules. */

export const FIELD_LABELS: Record<string, string> = {
  applicant_name: "Full name",
  date_of_birth: "Date of birth",
  mobile_number: "Mobile number",
  address: "Residential address",
  district: "District",
  annual_income: "Annual income (INR)",
  income_source: "Primary income source",
};

export const DOCUMENT_LABELS: Record<string, string> = {
  IDENTITY_PROOF: "Identity proof",
  ADDRESS_PROOF: "Address proof",
  INCOME_PROOF: "Income proof",
};

/** Citizen-facing POC verification labels — not production OCR claims. */
export const VERIFICATION_STATUS_LABELS: Record<string, string> = {
  VERIFIED: "Verification passed · Local POC",
  MISMATCH: "Verification failed · Details do not match",
  UNREADABLE: "Verification failed · Document unreadable",
};

export const VERIFICATION_POC_NOTE =
  "Demo verification uses local mock OCR; no external OCR service is used.";

export const STATE_LABELS: Record<string, string> = {
  LANGUAGE_SELECT: "Choose language",
  AUTHENTICATE: "Sign in",
  CONSENT: "Consent",
  SERVICE_SELECT: "Choose service",
  FORM_CAPTURE: "Application form",
  FIELD_CONFIRMATION: "Confirm your answer",
  DOCUMENT_CAPTURE: "Upload documents",
  DOCUMENT_REJECTED: "Document review",
  REVIEW_CONFIRM: "Review application",
  FEE_QUOTE: "Application fee",
  PAYMENT: "Payment",
  PAYMENT_FAILED: "Payment issue",
  CORRECTION: "Edit application",
  SUBMITTED: "Submitted",
  ESCALATED: "With officer",
  AUTH_FAILED: "Sign-in issue",
};

export function fieldLabel(name: string): string {
  return FIELD_LABELS[name] || name.replace(/_/g, " ");
}

export function documentLabel(code: string): string {
  return DOCUMENT_LABELS[code] || code.replace(/_/g, " ");
}

export function verificationStatusLabel(status: string | null | undefined): string {
  if (!status) return "";
  return VERIFICATION_STATUS_LABELS[status] || status.replace(/_/g, " ");
}

export function stateLabel(state: string): string {
  return STATE_LABELS[state] || "In progress";
}

export function applyForServiceLabel(displayName: string): string {
  return `Apply for ${displayName}`;
}

export function formatFee(amountPaise: number, currency: string): string {
  const amount = amountPaise / 100;
  if (currency === "INR") {
    return `₹${amount.toFixed(2)}`;
  }
  return `${amount.toFixed(2)} ${currency}`;
}

export function serviceDisplayName(
  code: string | undefined,
  services: Array<{ code: string; display_name: string }>,
): string {
  if (!code) return "Application";
  const match = services.find((item) => item.code === code);
  return match?.display_name || code.replace(/_/g, " ");
}

/** Convert native date input (YYYY-MM-DD) to backend DD/MM/YYYY. */
export function isoToBackendDate(iso: string): string {
  const [year, month, day] = iso.split("-");
  if (!year || !month || !day) return "";
  return `${day.padStart(2, "0")}/${month.padStart(2, "0")}/${year}`;
}

/** Convert backend DD/MM/YYYY to native date input value. */
export function backendDateToIso(dmy: string): string {
  const parts = dmy.split("/");
  if (parts.length !== 3) return "";
  const [day, month, year] = parts;
  return `${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`;
}
