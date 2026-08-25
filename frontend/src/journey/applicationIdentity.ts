/** Citizen-facing application identity copy. Never mention session tokens. */

export function ivrDocumentContinueCopy(applicationId: string): string {
  return (
    `Documents cannot be uploaded by phone. Continue on WhatsApp using Application ID ${applicationId}. ` +
    "This same-browser demo restores your existing application — you never enter a session token."
  );
}

export function whatsappContinueHint(): string {
  return (
    "Prefer Continue on WhatsApp from Apply or IVR. Or enter your Application ID if you started in this browser. " +
    "You never enter a session token — this demo only resumes same-browser sessions."
  );
}

export function missingSameBrowserHandoffMessage(): string {
  return (
    "No secure session was found for this Application ID in this browser. " +
    "Start from Apply or IVR here first, then Continue application — you do not enter a session token."
  );
}

export function citizenSeesSessionToken(text: string): boolean {
  return /access_token|X-Session-Token|your session token/i.test(text);
}
