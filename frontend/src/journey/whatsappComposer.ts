/** Pure helpers for WhatsApp simulator composer UX (presentation only). */

export type WaComposerAction = "mic" | "send";

/** Empty input → mic affordance; any typed text → Send. */
export function waComposerAction(input: string): WaComposerAction {
  return input.trim().length > 0 ? "send" : "mic";
}

const INTERNAL_DOC_CODE = /\b(IDENTITY_PROOF|ADDRESS_PROOF|INCOME_PROOF)\b/;

/** Citizen chat must not surface catalogue internal document codes. */
export function containsInternalDocumentCode(text: string): boolean {
  return INTERNAL_DOC_CODE.test(text || "");
}

export type WaAttachDraftState = {
  menuOpen: boolean;
  draftOpen: boolean;
  hasFile: boolean;
};

/** After a successful upload, attachment UI returns to the normal composer. */
export function resetAttachUiAfterUpload(): WaAttachDraftState {
  return { menuOpen: false, draftOpen: false, hasFile: false };
}

/** Draft opens only after a file is chosen — not when the menu is opened. */
export function attachDraftAfterFileSelected(fileSelected: boolean): boolean {
  return fileSelected;
}

/**
 * Browser autocomplete attrs for chat / resume fields.
 * Intentionally off so OTP, mobile numbers, and prior session answers
 * are not suggested from browser history in the composer.
 */
export function waMessageInputAutocomplete(): {
  autoComplete: "off";
  autoCorrect: "off";
  spellCheck: false;
} {
  return {
    autoComplete: "off",
    autoCorrect: "off",
    spellCheck: false,
  };
}

/** Native file input stays hidden; only opened via the attachment menu. */
export function fileInputShouldBePermanentlyVisible(): boolean {
  return false;
}

/** Compact composer layout: attach | message | mic-or-send (no permanent file control). */
export function waComposerLayoutSlots(): readonly ["attach", "message", "action"] {
  return ["attach", "message", "action"] as const;
}
