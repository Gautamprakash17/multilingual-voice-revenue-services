const API_BASE =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") || "";

export type HealthResponse = {
  status: string;
  service: string;
  version: string;
  environment: string;
};

export type ReadyResponse = {
  status: string;
  checks: { database: string };
};

export type JourneyResponse = {
  application_id: string;
  state: string;
  message: string;
  prompt?: string | null;
  access_token?: string | null;
  data?: Record<string, unknown>;
  error?: string | null;
  expected_format?: string | null;
  language?: string | null;
  channel?: string | null;
  transcript?: string | null;
  intent?: string | null;
  audio_b64?: string | null;
  audio_mime?: string | null;
};

async function parseJourney(res: Response): Promise<JourneyResponse> {
  const body = (await res.json()) as JourneyResponse | { error?: { message?: string } };
  if (!res.ok) {
    const msg =
      "error" in body && body.error && typeof body.error === "object"
        ? (body.error as { message?: string }).message
        : `Request failed (${res.status})`;
    throw new Error(msg || `Request failed (${res.status})`);
  }
  return body as JourneyResponse;
}

export type LanguageConfig = {
  code: string;
  display_name: string;
  native_name: string;
  stt_code: string;
  tts_code: string;
};

export type LanguageCatalogResponse = {
  default: string;
  languages: LanguageConfig[];
};

export type ServiceFieldConfig = {
  name: string;
  type: string;
  required: boolean;
  prompt?: string;
};

export type ServiceDocumentConfig = {
  code: string;
  label: string;
  required: boolean;
};

export type ServiceConfig = {
  code: string;
  display_name: string;
  description: string;
  fee?: {
    amount_paise: number;
    currency: string;
    description?: string;
  } | null;
  fields?: ServiceFieldConfig[];
  documents?: ServiceDocumentConfig[];
};

export type ServiceCatalogResponse = {
  services: ServiceConfig[];
};

export async function fetchLanguages(): Promise<LanguageCatalogResponse> {
  const res = await fetch(`${API_BASE}/api/v1/languages`);
  if (!res.ok) {
    throw new Error(`Language catalog failed (${res.status})`);
  }
  return res.json() as Promise<LanguageCatalogResponse>;
}

export async function fetchServices(): Promise<ServiceCatalogResponse> {
  const res = await fetch(`${API_BASE}/api/v1/services`);
  if (!res.ok) {
    throw new Error(`Service catalog failed (${res.status})`);
  }
  return res.json() as Promise<ServiceCatalogResponse>;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/v1/health`);
  if (!res.ok) {
    throw new Error(`Health check failed (${res.status})`);
  }
  return res.json() as Promise<HealthResponse>;
}

export async function fetchReady(): Promise<{
  ok: boolean;
  data: ReadyResponse;
}> {
  const res = await fetch(`${API_BASE}/api/v1/ready`);
  const data = (await res.json()) as ReadyResponse;
  return { ok: res.ok, data };
}

export async function startJourney(): Promise<JourneyResponse> {
  const res = await fetch(`${API_BASE}/api/v1/journey/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ channel: "web" }),
  });
  return parseJourney(res);
}

export async function sendJourneyMessage(
  applicationId: string,
  token: string,
  text: string,
): Promise<JourneyResponse> {
  const res = await fetch(`${API_BASE}/api/v1/journey/${applicationId}/message`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-Token": token,
    },
    body: JSON.stringify({ text }),
  });
  return parseJourney(res);
}

export async function postConsent(
  applicationId: string,
  token: string,
  granted: boolean,
): Promise<JourneyResponse> {
  const res = await fetch(`${API_BASE}/api/v1/journey/${applicationId}/consent`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-Token": token,
    },
    body: JSON.stringify({ granted }),
  });
  return parseJourney(res);
}

export async function getJourney(
  applicationId: string,
  token: string,
): Promise<JourneyResponse> {
  const res = await fetch(`${API_BASE}/api/v1/journey/${applicationId}`, {
    headers: { "X-Session-Token": token },
  });
  return parseJourney(res);
}

export async function uploadDocument(
  applicationId: string,
  token: string,
  documentCode: string,
  file: File,
): Promise<JourneyResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(
    `${API_BASE}/api/v1/journey/${applicationId}/documents/${documentCode}`,
    {
      method: "POST",
      headers: { "X-Session-Token": token },
      body: form,
    },
  );
  return parseJourney(res);
}

export async function startChannel(channel: string): Promise<JourneyResponse> {
  const res = await fetch(`${API_BASE}/api/v1/channels/${channel}/start`, {
    method: "POST",
  });
  return parseJourney(res);
}

export async function sendChannelMessage(
  channel: string,
  applicationId: string,
  token: string,
  payload: {
    text?: string;
    modality?: string;
    language?: string;
    dtmf?: string;
    audio_b64?: string;
    transcript?: string;
  },
): Promise<JourneyResponse> {
  const res = await fetch(`${API_BASE}/api/v1/channels/${channel}/message`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-Token": token,
    },
    body: JSON.stringify({
      application_id: applicationId,
      modality: payload.modality || "text",
      ...payload,
    }),
  });
  return parseJourney(res);
}

export async function resumeChannel(
  applicationId: string,
  token: string,
  channel: string,
): Promise<JourneyResponse> {
  const res = await fetch(`${API_BASE}/api/v1/channels/resume`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-Token": token,
    },
    body: JSON.stringify({ application_id: applicationId, channel }),
  });
  return parseJourney(res);
}

export async function fetchMetrics(): Promise<Record<string, unknown>> {
  const res = await fetch(`${API_BASE}/api/v1/metrics`);
  if (!res.ok) throw new Error("Metrics unavailable");
  return res.json() as Promise<Record<string, unknown>>;
}

export async function getReceipt(
  applicationId: string,
  token: string,
): Promise<JourneyResponse> {
  const res = await fetch(`${API_BASE}/api/v1/journey/${applicationId}/receipt`, {
    headers: { "X-Session-Token": token },
  });
  return parseJourney(res);
}

export type OfficerApplication = {
  application_id: string;
  service_code: string;
  journey_state: string;
  processing_status: string;
  language?: string | null;
  escalated: boolean;
  payment_completed: boolean;
  payment_ref?: string | null;
  correction_notes?: string | null;
  documents: Array<Record<string, unknown>>;
  fields_present: string[];
  created_at?: string | null;
};

export type OfficerHistoryItem = {
  application_id: string;
  service_code: string;
  service_display_name: string;
  processing_status: string;
  journey_state: string;
  last_action: string;
  last_action_label: string;
  action_at: string;
  escalated: boolean;
};

async function officerFetch(
  path: string,
  officerToken: string,
  init?: RequestInit,
): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Officer-Token": officerToken,
      ...(init?.headers || {}),
    },
  });
}

export async function fetchOfficerQueue(
  officerToken: string,
): Promise<OfficerApplication[]> {
  const res = await officerFetch("/api/v1/officer/queue", officerToken);
  if (!res.ok) {
    const body = (await res.json()) as { error?: { message?: string } };
    throw new Error(body.error?.message || `Officer queue failed (${res.status})`);
  }
  return res.json() as Promise<OfficerApplication[]>;
}

export async function fetchOfficerHistory(
  officerToken: string,
): Promise<OfficerHistoryItem[]> {
  const res = await officerFetch("/api/v1/officer/history", officerToken);
  if (!res.ok) {
    const body = (await res.json()) as { error?: { message?: string } };
    throw new Error(body.error?.message || `Officer history failed (${res.status})`);
  }
  return res.json() as Promise<OfficerHistoryItem[]>;
}

export async function fetchOfficerApplication(
  officerToken: string,
  applicationId: string,
): Promise<OfficerApplication> {
  const res = await officerFetch(`/api/v1/officer/${applicationId}`, officerToken);
  if (!res.ok) {
    const body = (await res.json()) as { error?: { message?: string } };
    throw new Error(body.error?.message || `Officer detail failed (${res.status})`);
  }
  return res.json() as Promise<OfficerApplication>;
}

export async function officerAction(
  officerToken: string,
  applicationId: string,
  action: "approve" | "reject" | "request-correction" | "escalate",
  body?: { reason?: string; notes?: string; target_fields?: string[] },
): Promise<OfficerApplication> {
  const res = await officerFetch(
    `/api/v1/officer/${applicationId}/${action}`,
    officerToken,
    { method: "POST", body: JSON.stringify(body || {}) },
  );
  if (!res.ok) {
    const payload = (await res.json()) as { error?: { message?: string } };
    throw new Error(payload.error?.message || `Officer action failed (${res.status})`);
  }
  return res.json() as Promise<OfficerApplication>;
}

/** Encode a POC voice marker understood by MockSTTProvider. */
export function encodePocVoice(transcript: string): string {
  const bytes = new TextEncoder().encode(`POCSTT:${transcript}`);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary);
}
