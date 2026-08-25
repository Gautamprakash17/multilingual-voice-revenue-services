import { describe, expect, it } from "vitest";
import {
  continueApplicationLabel,
  emptyNotificationCopy,
  formatNotificationTime,
  notificationEventLabel,
  notificationTitle,
  notificationContainsSensitiveLeak,
  notificationInboxState,
  notificationLoadingCopy,
  notificationSender,
  shouldShowContinueApplication,
  shouldShowStatusInbox,
  shouldShowViewCertificate,
  simulatedNotificationLabel,
  viewCertificateLabel,
  type CitizenNotification,
} from "./citizenNotifications";

function sample(overrides: Partial<CitizenNotification> = {}): CitizenNotification {
  return {
    id: "n1",
    application_id: "INC-2284",
    event_type: "UNDER_REVIEW",
    message: "Your Income Certificate application INC-2284 is under review.",
    channels: ["sms", "whatsapp"],
    delivery_status: "simulated",
    created_at: "2026-08-26T10:00:00+00:00",
    simulated: true,
    ...overrides,
  };
}

describe("notification inbox rendering helpers", () => {
  it("shows sender, application id, status, and timestamp", () => {
    const item = sample();
    expect(notificationSender()).toBe("Revenue Services");
    expect(item.application_id).toBe("INC-2284");
    expect(item.event_type).toBe("UNDER_REVIEW");
    expect(notificationEventLabel(item.event_type)).toBe("Under review");
    expect(notificationTitle("ISSUED")).toBe("Certificate ready");
    expect(notificationTitle("NEEDS_CORRECTION")).toBe("Action required");
    expect(item.message).toContain("INC-2284");
    expect(formatNotificationTime(item.created_at)).toContain("2026");
    expect(simulatedNotificationLabel().toLowerCase()).toContain("simulated");
  });

  it("renders empty, loading, and error states", () => {
    expect(notificationInboxState({ loading: true, error: null, items: [] })).toBe("loading");
    expect(notificationInboxState({ loading: false, error: "failed", items: [] })).toBe("error");
    expect(notificationInboxState({ loading: false, error: null, items: [] })).toBe("empty");
    expect(
      notificationInboxState({ loading: false, error: null, items: [sample()] }),
    ).toBe("ready");
    expect(emptyNotificationCopy().length).toBeGreaterThan(0);
    expect(notificationLoadingCopy().length).toBeGreaterThan(0);
  });

  it("shows the issued certificate action only when securely available", () => {
    expect(
      shouldShowViewCertificate(
        sample({ event_type: "ISSUED", certificate_available: true }),
      ),
    ).toBe(true);
    expect(
      shouldShowViewCertificate(
        sample({ event_type: "ISSUED", certificate_available: false }),
      ),
    ).toBe(false);
    expect(shouldShowViewCertificate(sample({ event_type: "UNDER_REVIEW" }))).toBe(false);
    expect(viewCertificateLabel()).toBe("View Certificate");
  });

  it("shows continue for correction notifications", () => {
    expect(
      shouldShowContinueApplication(
        sample({ event_type: "NEEDS_CORRECTION", continue_available: true }),
      ),
    ).toBe(true);
    expect(continueApplicationLabel()).toBe("Continue application");
  });

  it("keeps the phone inbox hidden until OTP or a status message exists", () => {
    expect(
      shouldShowStatusInbox({ otpActive: false, notificationCount: 0, error: null }),
    ).toBe(false);
    expect(
      shouldShowStatusInbox({ otpActive: true, notificationCount: 0, error: null }),
    ).toBe(true);
    expect(
      shouldShowStatusInbox({ otpActive: false, notificationCount: 2, error: null }),
    ).toBe(true);
  });

  it("does not treat notification copy as a credential or storage path", () => {
    const safe = sample();
    expect(notificationContainsSensitiveLeak(safe.message)).toBe(false);
    expect(notificationContainsSensitiveLeak("token X-Session-Token abc")).toBe(true);
    expect(notificationContainsSensitiveLeak("file /data/documents/doc_aa")).toBe(true);
    expect(notificationContainsSensitiveLeak("storage_key=doc_1")).toBe(true);
  });
});
