/** Same-browser session handoff for cross-channel resume (POC).

The backend still requires X-Session-Token. Citizens never type it —
Apply stores the token in sessionStorage; WhatsApp reads it internally.
*/

const HANDOFF_KEY = "rvs_channel_handoff";
const HANDOFF_BY_APP_PREFIX = "rvs_channel_handoff:";

export type SessionHandoff = {
  applicationId: string;
  accessToken: string;
  savedAt: number;
};

export type WhatsAppResumeNavState = {
  resumeFromWeb: true;
  applicationId: string;
};

export function normalizeCitizenApplicationId(value: string): string {
  return value.trim().toUpperCase();
}

export function storeSessionHandoff(applicationId: string, accessToken: string): void {
  const id = normalizeCitizenApplicationId(applicationId);
  if (!id || !accessToken) return;
  const payload: SessionHandoff = {
    applicationId: id,
    accessToken,
    savedAt: Date.now(),
  };
  try {
    sessionStorage.setItem(HANDOFF_KEY, JSON.stringify(payload));
    sessionStorage.setItem(`${HANDOFF_BY_APP_PREFIX}${id}`, JSON.stringify(payload));
  } catch {
    // sessionStorage may be unavailable — resume from Apply button still uses router state
  }
}

export function lookupSessionHandoff(applicationId: string): string | null {
  const id = normalizeCitizenApplicationId(applicationId);
  if (!id) return null;
  try {
    const raw = sessionStorage.getItem(`${HANDOFF_BY_APP_PREFIX}${id}`);
    if (raw) {
      const parsed = JSON.parse(raw) as SessionHandoff;
      if (parsed.accessToken && parsed.applicationId === id) return parsed.accessToken;
    }
    const latest = sessionStorage.getItem(HANDOFF_KEY);
    if (latest) {
      const parsed = JSON.parse(latest) as SessionHandoff;
      if (parsed.accessToken && parsed.applicationId === id) return parsed.accessToken;
    }
  } catch {
    return null;
  }
  return null;
}

export function peekLatestHandoff(): SessionHandoff | null {
  try {
    const raw = sessionStorage.getItem(HANDOFF_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as SessionHandoff;
  } catch {
    return null;
  }
}
