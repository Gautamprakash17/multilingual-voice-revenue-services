import { useEffect, useRef, useState } from "react";
import { fetchDemoSms, type DemoSmsResponse } from "../api/client";
import {
  continueApplicationLabel,
  emptyNotificationCopy,
  formatNotificationTime,
  notificationInboxState,
  notificationLoadingCopy,
  notificationSender,
  notificationEventLabel,
  notificationTitle,
  shouldShowContinueApplication,
  shouldShowStatusInbox,
  shouldShowViewCertificate,
  simulatedNotificationLabel,
  smsChannelLabel,
  useCitizenNotifications,
  viewCertificateLabel,
} from "../journey/citizenNotifications";
import { SYNTHETIC_OTP_LABEL, formatOtpForDisplay } from "../journey/phoneSimulator";

type Props = {
  applicationId: string;
  token: string;
  otpActive: boolean;
  onViewCertificate?: () => void;
  onContinueApplication?: () => void;
};

export default function PhoneSimulator({
  applicationId,
  token,
  otpActive,
  onViewCertificate,
  onContinueApplication,
}: Props) {
  const [sms, setSms] = useState<DemoSmsResponse | null>(null);
  const [otpError, setOtpError] = useState<string | null>(null);
  const { items: notifications, loading: inboxLoading, error: inboxError } =
    useCitizenNotifications(applicationId, token);
  const knownIds = useRef(new Set<string>());
  const [unreadIds, setUnreadIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    const fresh = new Set<string>();
    for (const item of notifications) {
      if (!knownIds.current.has(item.id)) {
        knownIds.current.add(item.id);
        fresh.add(item.id);
      }
    }
    if (fresh.size === 0) return;
    setUnreadIds((prev) => new Set([...prev, ...fresh]));
  }, [notifications]);

  useEffect(() => {
    if (!otpActive || !applicationId || !token) {
      setSms(null);
      return;
    }
    let cancelled = false;
    void fetchDemoSms(applicationId, token)
      .then((payload) => {
        if (!cancelled) {
          setSms(payload.active ? payload : null);
          setOtpError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setOtpError(err instanceof Error ? err.message : "Could not load demo SMS");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [otpActive, applicationId, token]);

  const visible = shouldShowStatusInbox({
    otpActive,
    notificationCount: notifications.length,
    error: inboxError,
  });
  if (!visible) {
    return null;
  }

  const inboxState = notificationInboxState({
    loading: inboxLoading,
    error: inboxError,
    items: notifications,
  });
  const code = sms?.code || "";

  return (
    <aside className="phone-sim" aria-live="polite" aria-label="Synthetic demo phone">
      <div className="phone-sim-notch" aria-hidden="true" />
      <p className="phone-sim-banner">{simulatedNotificationLabel()}</p>
      {otpActive && (
        <div className="phone-sim-otp">
          <p className="phone-sim-from">📱 {sms?.from || notificationSender()}</p>
          <p className="phone-sim-body">Your verification code</p>
          <p className="phone-sim-code">{code ? formatOtpForDisplay(code) : "••••••"}</p>
          <p className="phone-sim-label">{sms?.label || SYNTHETIC_OTP_LABEL}</p>
          {otpError && <p className="phone-sim-error">{otpError}</p>}
        </div>
      )}
      <div className="phone-sim-thread" role="log">
        {inboxState === "loading" && <p className="phone-sim-body">{notificationLoadingCopy()}</p>}
        {inboxState === "error" && <p className="phone-sim-error">{inboxError}</p>}
        {inboxState === "empty" && otpActive && (
          <p className="phone-sim-body">{emptyNotificationCopy()}</p>
        )}
        {notifications.map((item) => (
          <article
            key={item.id}
            className={`phone-sim-sms${unreadIds.has(item.id) ? " unread" : ""}`}
            onClick={() => {
              setUnreadIds((prev) => {
                if (!prev.has(item.id)) return prev;
                const next = new Set(prev);
                next.delete(item.id);
                return next;
              });
            }}
          >
            <p className="phone-sim-from">
              {notificationSender()}
              <span className="phone-sim-channel">{smsChannelLabel()}</span>
            </p>
            <p className="phone-sim-title">
              {item.event_type === "ISSUED"
                ? "✓ Certificate Issued"
                : notificationTitle(item.event_type)}
            </p>
            <p className="phone-sim-meta">
              Application {item.application_id}
            </p>
            <p className="phone-sim-meta">
              Status: {notificationEventLabel(item.event_type)}
            </p>
            <p className="phone-sim-body">{item.message}</p>
            {item.created_at && (
              <time className="phone-sim-label" dateTime={item.created_at}>
                {formatNotificationTime(item.created_at)}
              </time>
            )}
            {shouldShowViewCertificate(item) && onViewCertificate && (
              <button type="button" className="phone-sim-action" onClick={onViewCertificate}>
                {viewCertificateLabel()}
              </button>
            )}
            {shouldShowContinueApplication(item) && onContinueApplication && (
              <button type="button" className="phone-sim-action" onClick={onContinueApplication}>
                {continueApplicationLabel()}
              </button>
            )}
          </article>
        ))}
      </div>
    </aside>
  );
}
