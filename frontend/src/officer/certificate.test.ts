import { describe, expect, it } from "vitest";
import {
  issuedCertificateErrorMessage,
  issuedCertificateHeading,
  issuedCertificateMissingMessage,
  issuedCertificateUiState,
  isIssuedCertificateDoc,
  certificateDemoDisclaimer,
  certificateIssuedTitle,
  certificateReadyCopy,
} from "./certificate";

describe("issued certificate UI", () => {
  it("hides the section when the application is not issued", () => {
    expect(
      issuedCertificateUiState({
        processingStatus: "UNDER_REVIEW",
        certificate: { available: true },
        loading: false,
        error: null,
      }),
    ).toBe("hidden");
    expect(
      issuedCertificateUiState({
        processingStatus: "REJECTED",
        certificate: null,
        loading: false,
        error: null,
      }),
    ).toBe("hidden");
  });

  it("shows ready, loading, missing, and error states for ISSUED applications", () => {
    expect(
      issuedCertificateUiState({
        processingStatus: "ISSUED",
        certificate: { available: true, filename: "income-certificate-INC-1.pdf" },
        loading: false,
        error: null,
      }),
    ).toBe("ready");
    expect(
      issuedCertificateUiState({
        processingStatus: "ISSUED",
        certificate: { available: true },
        loading: true,
        error: null,
      }),
    ).toBe("loading");
    expect(
      issuedCertificateUiState({
        processingStatus: "ISSUED",
        certificate: null,
        loading: false,
        error: null,
      }),
    ).toBe("missing");
    expect(
      issuedCertificateUiState({
        processingStatus: "ISSUED",
        certificate: { available: true },
        loading: false,
        error: "failed",
      }),
    ).toBe("error");
  });

  it("exposes view/download copy without storage paths", () => {
    expect(issuedCertificateHeading()).toBe("Issued Certificate");
    expect(issuedCertificateMissingMessage()).not.toMatch(/storage|doc_/i);
    expect(issuedCertificateErrorMessage()).not.toMatch(/token|path/i);
    expect(isIssuedCertificateDoc("ISSUED_CERTIFICATE")).toBe(true);
    expect(isIssuedCertificateDoc("IDENTITY_PROOF")).toBe(false);
    expect(certificateIssuedTitle()).toBe("Certificate issued");
    expect(certificateReadyCopy("Income Certificate")).toContain("Income Certificate");
    expect(certificateDemoDisclaimer()).toMatch(/DEMO \/ POC/i);
  });
});
