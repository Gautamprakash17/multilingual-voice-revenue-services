import { describe, expect, it } from "vitest";
import {
  attachDraftAfterFileSelected,
  containsInternalDocumentCode,
  fileInputShouldBePermanentlyVisible,
  resetAttachUiAfterUpload,
  waComposerAction,
  waComposerLayoutSlots,
  waMessageInputAutocomplete,
} from "./whatsappComposer";

describe("normal message composer", () => {
  it("uses compact attach | message | action layout", () => {
    expect(waComposerLayoutSlots()).toEqual(["attach", "message", "action"]);
  });

  it("does not keep the native file input permanently visible", () => {
    expect(fileInputShouldBePermanentlyVisible()).toBe(false);
  });
});

describe("waComposerAction", () => {
  it("shows mic when input is empty", () => {
    expect(waComposerAction("")).toBe("mic");
    expect(waComposerAction("   ")).toBe("mic");
  });

  it("shows Send when text is entered", () => {
    expect(waComposerAction("en")).toBe("send");
    expect(waComposerAction(" yes ")).toBe("send");
  });
});

describe("WhatsApp attachment draft", () => {
  it("does not open draft until a file is selected (menu alone is not enough)", () => {
    expect(attachDraftAfterFileSelected(false)).toBe(false);
  });

  it("opens draft after Document file selection", () => {
    expect(attachDraftAfterFileSelected(true)).toBe(true);
  });

  it("selected document appears as a draft only when a file exists", () => {
    const withFile = { menuOpen: false, draftOpen: true, hasFile: true };
    expect(withFile.draftOpen && withFile.hasFile).toBe(true);
    expect(attachDraftAfterFileSelected(withFile.hasFile)).toBe(true);
  });

  it("returns to normal composer after successful upload", () => {
    expect(resetAttachUiAfterUpload()).toEqual({
      menuOpen: false,
      draftOpen: false,
      hasFile: false,
    });
  });
});

describe("internal document codes", () => {
  it("detects catalogue codes that must not appear to citizens", () => {
    expect(containsInternalDocumentCode("Upload IDENTITY_PROOF")).toBe(true);
    expect(containsInternalDocumentCode("Upload ADDRESS_PROOF")).toBe(true);
    expect(containsInternalDocumentCode("Upload INCOME_PROOF")).toBe(true);
    expect(containsInternalDocumentCode("Identity proof uploaded")).toBe(false);
    expect(containsInternalDocumentCode("Please upload your Identity proof document.")).toBe(
      false,
    );
  });
});

describe("browser autocomplete", () => {
  it("disables autocomplete on sensitive/session message fields", () => {
    const attrs = waMessageInputAutocomplete();
    expect(attrs.autoComplete).toBe("off");
    expect(attrs.autoCorrect).toBe("off");
    expect(attrs.spellCheck).toBe(false);
  });
});
