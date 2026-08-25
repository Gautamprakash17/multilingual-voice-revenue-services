/** Officer UI helpers — labels and list view mode (no API calls). */

export type OfficerListMode = "applications" | "history";

export function formatOfficerActionAt(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function officerHistoryEmptyMessage(count: number, loading: boolean): string {
  if (loading) return "Loading history…";
  if (count === 0) return "No completed officer actions yet.";
  return "";
}

export function officerQueueEmptyMessage(count: number, loading: boolean): string {
  if (loading) return "Loading applications…";
  if (count === 0) return "No applications yet.";
  return "";
}

export function isOfficerHistoryMode(mode: OfficerListMode): boolean {
  return mode === "history";
}

export function formatOfficerChannel(channel: string | null | undefined): string {
  if (!channel) return "—";
  const key = channel.toLowerCase();
  if (key === "whatsapp") return "WhatsApp";
  if (key === "ivr") return "IVR";
  if (key === "web") return "Web";
  return channel;
}

export type OfficerStatusCounts = {
  pending: number;
  underReview: number;
  needsCorrection: number;
  issued: number;
  rejected: number;
};

export function officerStatusCounts(
  queue: Array<{ processing_status: string }>,
  history: Array<{ processing_status: string }>,
): OfficerStatusCounts {
  const count = (rows: Array<{ processing_status: string }>, status: string) =>
    rows.filter((row) => row.processing_status.toUpperCase() === status).length;
  return {
    pending: count(queue, "SUBMITTED"),
    underReview: count(queue, "UNDER_REVIEW"),
    needsCorrection: count(queue, "NEEDS_CORRECTION"),
    issued: count(history, "ISSUED"),
    rejected: count(history, "REJECTED"),
  };
}

export function officerApplicantSummary(fieldsPresent: string[] | null | undefined): string {
  if (!fieldsPresent || fieldsPresent.length === 0) return "—";
  return fieldsPresent.includes("applicant_name") ? "On file" : "Partial";
}
