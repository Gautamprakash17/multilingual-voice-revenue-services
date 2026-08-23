/** Presentation helpers for citizen application form controls. */

import type { ServiceFieldConfig } from "../api/client";
import { backendDateToIso, fieldLabel, isoToBackendDate } from "./labels";

export type FormDraft = Record<string, string>;

export function emptyDraft(fields: ServiceFieldConfig[]): FormDraft {
  const draft: FormDraft = {};
  for (const field of fields) {
    draft[field.name] = "";
  }
  return draft;
}

export function draftFromCaptured(
  fields: ServiceFieldConfig[],
  captured: Record<string, unknown> | null | undefined,
): FormDraft {
  const draft = emptyDraft(fields);
  if (!captured) return draft;
  for (const field of fields) {
    const raw = captured[field.name];
    if (raw == null) continue;
    const text = String(raw);
    if (field.type === "date" || field.name === "date_of_birth") {
      draft[field.name] = backendDateToIso(text) || text;
    } else {
      draft[field.name] = text;
    }
  }
  return draft;
}

/** Convert a draft control value into the backend journey message format. */
export function draftValueForBackend(field: ServiceFieldConfig, draftValue: string): string {
  const trimmed = (draftValue || "").trim();
  if (!trimmed) return "";
  if (field.type === "date" || field.name === "date_of_birth") {
    if (/^\d{4}-\d{2}-\d{2}$/.test(trimmed)) {
      return isoToBackendDate(trimmed);
    }
  }
  return trimmed;
}

/**
 * First required catalog field with no completed draft value.
 * Optional fields are ignored. Never invents placeholders.
 */
export function findFirstMissingRequired(
  fields: ServiceFieldConfig[],
  draft: FormDraft,
): ServiceFieldConfig | null {
  for (const field of fields) {
    if (!field.required) continue;
    if (!draftValueForBackend(field, draft[field.name] || "")) {
      return field;
    }
  }
  return null;
}

/** Citizen-facing message for a missing required catalog field. */
export function missingRequiredMessage(field: ServiceFieldConfig): string {
  const label = citizenFieldCaption(field).toLowerCase();
  return `Please enter your ${label}.`;
}

export function fieldInputType(field: ServiceFieldConfig): string {
  if (field.type === "date" || field.name === "date_of_birth") return "date";
  if (field.type === "number" || field.name === "annual_income") return "number";
  if (field.type === "mobile" || field.name === "mobile_number") return "tel";
  return "text";
}

export function fieldInputMode(
  field: ServiceFieldConfig,
): "text" | "numeric" | "tel" | "search" | "email" | "url" | "decimal" | undefined {
  if (field.type === "number" || field.name === "annual_income") return "numeric";
  if (field.type === "mobile" || field.name === "mobile_number") return "numeric";
  return undefined;
}

export function citizenFieldCaption(field: ServiceFieldConfig): string {
  return fieldLabel(field.name);
}
