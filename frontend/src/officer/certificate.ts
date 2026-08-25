/** Officer issued-certificate UI helpers — no API calls. */

export const ISSUED_CERTIFICATE_CODE = "ISSUED_CERTIFICATE";

export type IssuedCertificateMeta = {
  code?: string;
  available?: boolean;
  filename?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  issued_at?: string | null;
};

export type CertificateUiState = "hidden" | "ready" | "missing" | "loading" | "error";

export function issuedCertificateUiState(opts: {
  processingStatus: string | null | undefined;
  certificate: IssuedCertificateMeta | null | undefined;
  loading: boolean;
  error: string | null;
}): CertificateUiState {
  if ((opts.processingStatus || "").toUpperCase() !== "ISSUED") return "hidden";
  if (opts.loading) return "loading";
  if (opts.error) return "error";
  if (opts.certificate?.available) return "ready";
  return "missing";
}

export function isIssuedCertificateDoc(code: unknown): boolean {
  return String(code || "").toUpperCase() === ISSUED_CERTIFICATE_CODE;
}

export function issuedCertificateHeading(): string {
  return "Issued Certificate";
}

export function issuedCertificateMissingMessage(): string {
  return "This application is issued, but the certificate PDF is not available.";
}

export function issuedCertificateErrorMessage(): string {
  return "The certificate PDF could not be loaded. Try again.";
}

export function issuedCertificateLoadingMessage(): string {
  return "Loading certificate…";
}

export function certificateIssuedTitle(): string {
  return "Certificate issued";
}

export function certificateReadyCopy(serviceName: string): string {
  return `Your ${serviceName} is ready.`;
}

export function certificateDemoDisclaimer(): string {
  return "DEMO / POC — not an official government certificate.";
}
