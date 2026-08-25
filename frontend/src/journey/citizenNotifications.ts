/** Citizen status-notification inbox helpers — simulated local delivery only. */

import { useEffect, useState } from "react";
import {
  fetchCitizenNotifications,
  type CitizenNotification,
  type CitizenNotificationsResponse,
} from "../api/client";

export type { CitizenNotification, CitizenNotificationsResponse };

export type NotificationInboxState = "loading" | "error" | "empty" | "ready";

export function notificationSender(): string {
  return "Revenue Services";
}

export function simulatedNotificationLabel(): string {
  return "Simulated local notification";
}

export function formatNotificationTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleString();
}

export function notificationInboxState(opts: {
  loading: boolean;
  error: string | null;
  items: CitizenNotification[];
}): NotificationInboxState {
  if (opts.error) return "error";
  if (opts.loading && opts.items.length === 0) return "loading";
  if (opts.items.length === 0) return "empty";
  return "ready";
}

export function shouldShowStatusInbox(opts: {
  otpActive: boolean;
  notificationCount: number;
  error: string | null;
}): boolean {
  return opts.otpActive || opts.notificationCount > 0 || Boolean(opts.error);
}

export function shouldShowViewCertificate(item: CitizenNotification): boolean {
  return item.event_type === "ISSUED" && item.certificate_available === true;
}

export function shouldShowContinueApplication(item: CitizenNotification): boolean {
  return item.event_type === "NEEDS_CORRECTION" && item.continue_available === true;
}

export function notificationContainsSensitiveLeak(text: string): boolean {
  const lower = text.toLowerCase();
  return (
    lower.includes("x-session-token") ||
    lower.includes("access_token") ||
    lower.includes("storage_key") ||
    lower.includes("/data/documents") ||
    /doc_[0-9a-f]{20,}/i.test(text)
  );
}

export function emptyNotificationCopy(): string {
  return "No status messages yet.";
}

export function notificationLoadingCopy(): string {
  return "Loading messages…";
}

export function viewCertificateLabel(): string {
  return "View Certificate";
}

export function continueApplicationLabel(): string {
  return "Continue application";
}

export function smsChannelLabel(): string {
  return "SMS";
}

export function whatsappChannelLabel(): string {
  return "WhatsApp";
}

export function emailChannelLabel(): string {
  return "Email";
}

export function notificationEventLabel(eventType: string | null | undefined): string {
  const key = (eventType || "").toUpperCase();
  const labels: Record<string, string> = {
    SUBMITTED: "Submitted",
    UNDER_REVIEW: "Under review",
    NEEDS_CORRECTION: "Correction required",
    ISSUED: "Issued",
    REJECTED: "Rejected",
  };
  return labels[key] || (eventType ? eventType.replace(/_/g, " ") : "Update");
}

export function notificationTitle(eventType: string | null | undefined): string {
  const key = (eventType || "").toUpperCase();
  if (key === "SUBMITTED") return "Application submitted";
  if (key === "UNDER_REVIEW") return "Under review";
  if (key === "NEEDS_CORRECTION") return "Action required";
  if (key === "ISSUED") return "Certificate ready";
  if (key === "REJECTED") return "Application rejected";
  return notificationEventLabel(eventType);
}

export function useCitizenNotifications(
  applicationId: string,
  token: string,
): {
  items: CitizenNotification[];
  loading: boolean;
  error: string | null;
} {
  const [items, setItems] = useState<CitizenNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!applicationId || !token) {
      setItems([]);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    let first = true;
    const load = () => {
      if (first) {
        setLoading(true);
      }
      void fetchCitizenNotifications(applicationId, token)
        .then((payload: CitizenNotificationsResponse) => {
          if (!cancelled) {
            setItems(payload.notifications || []);
            setError(null);
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : "Could not load notifications");
          }
        })
        .finally(() => {
          first = false;
          if (!cancelled) {
            setLoading(false);
          }
        });
    };
    load();
    const timer = window.setInterval(load, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [applicationId, token]);

  return { items, loading, error };
}
