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
