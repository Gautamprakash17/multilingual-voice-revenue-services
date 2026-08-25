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

export function processingStatusLabel(status: string | null | undefined): string {
  const key = (status || "").toUpperCase();
  const labels: Record<string, string> = {
    DRAFT: "Draft",
    SUBMITTED: "Submitted",
    UNDER_REVIEW: "Under review",
    NEEDS_CORRECTION: "Correction required",
    APPROVED: "Approved",
    ISSUED: "Issued",
    REJECTED: "Rejected",
  };
  if (labels[key]) return labels[key];
  if (!status) return "In progress";
  return status.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

export function processingStatusBadgeClass(status: string | null | undefined): string {
  const key = (status || "").toUpperCase();
  if (key === "ISSUED" || key === "APPROVED" || key === "SUBMITTED") return "badge badge-success";
  if (key === "REJECTED") return "badge badge-error";
  if (key === "NEEDS_CORRECTION") return "badge badge-warning";
  return "badge badge-info";
}

export type StatusLifecycleStep = {
  id: string;
  label: string;
  phase: "done" | "current" | "upcoming";
};

/** Presentation-only lifecycle for existing processing_status values. */
export function statusLifecycleSteps(
  status: string | null | undefined,
): StatusLifecycleStep[] {
  const key = (status || "").toUpperCase();
  if (!key || key === "DRAFT") return [];

  const showCorrection = key === "NEEDS_CORRECTION";
  const terminalId =
    key === "REJECTED" ? "REJECTED" : key === "ISSUED" || key === "APPROVED" ? "ISSUED" : "ISSUED";

  const ids: string[] = ["SUBMITTED", "UNDER_REVIEW"];
  if (showCorrection) ids.push("NEEDS_CORRECTION");
  ids.push(terminalId);

  const rank: Record<string, number> = {
    SUBMITTED: 0,
    UNDER_REVIEW: 1,
    NEEDS_CORRECTION: 2,
    ISSUED: showCorrection ? 3 : 2,
    REJECTED: showCorrection ? 3 : 2,
    APPROVED: showCorrection ? 3 : 2,
  };
  const currentRank = rank[key] ?? 1;

  return ids.map((id) => {
    const stepRank = rank[id] ?? 0;
    let phase: StatusLifecycleStep["phase"] = "upcoming";
    if (id === key || (id === "ISSUED" && key === "APPROVED")) phase = "current";
    else if (stepRank < currentRank) phase = "done";
    return {
      id,
      label: processingStatusLabel(id),
      phase,
    };
  });
}

export function citizenServiceBlurb(description: string | null | undefined): string {
  const cleaned = String(description || "")
    .replace(/POC service definition[^.]*\.?/gi, "")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned || "Apply through a guided digital journey.";
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
