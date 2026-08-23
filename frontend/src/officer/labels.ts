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
  if (count === 0) return "No applications requiring review. Refresh to load.";
  return "";
}

export function isOfficerHistoryMode(mode: OfficerListMode): boolean {
  return mode === "history";
}
