"""In-process POC metrics — no Prometheus stack."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MetricsStore:
    sessions_by_channel: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    sessions_by_language: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    stt_success: int = 0
    stt_failure: int = 0
    nlu_success: int = 0
    nlu_failure: int = 0
    channel_errors: int = 0
    escalations: int = 0
    corrections: int = 0
    payment_success: int = 0
    payment_failure: int = 0
    payment_timeout: int = 0
    doc_verified: int = 0
    doc_mismatch: int = 0
    doc_unreadable: int = 0
    status_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latencies_ms: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_session(self, channel: str, language: str | None) -> None:
        with self._lock:
            self.sessions_by_channel[channel] += 1
            if language:
                self.sessions_by_language[language] += 1

    def record_stt(self, ok: bool, latency_ms: float | None = None) -> None:
        with self._lock:
            if ok:
                self.stt_success += 1
            else:
                self.stt_failure += 1
            if latency_ms is not None:
                self.latencies_ms.append(latency_ms)

    def record_nlu(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self.nlu_success += 1
            else:
                self.nlu_failure += 1

    def record_channel_error(self) -> None:
        with self._lock:
            self.channel_errors += 1

    def record_escalation(self) -> None:
        with self._lock:
            self.escalations += 1

    def record_correction(self) -> None:
        with self._lock:
            self.corrections += 1

    def record_payment(self, outcome: str) -> None:
        with self._lock:
            key = outcome.upper()
            if key == "SUCCESS":
                self.payment_success += 1
            elif key == "TIMEOUT":
                self.payment_timeout += 1
            else:
                self.payment_failure += 1

    def record_doc_verification(self, outcome: str) -> None:
        with self._lock:
            key = outcome.upper()
            if key == "VERIFIED":
                self.doc_verified += 1
            elif key == "MISMATCH":
                self.doc_mismatch += 1
            elif key == "UNREADABLE":
                self.doc_unreadable += 1

    def record_status(self, status: str) -> None:
        with self._lock:
            self.status_counts[status] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            lats = sorted(self.latencies_ms)
            p50 = lats[len(lats) // 2] if lats else None
            avg = sum(lats) / len(lats) if lats else None
            return {
                "sessions_by_channel": dict(self.sessions_by_channel),
                "sessions_by_language": dict(self.sessions_by_language),
                "stt_success": self.stt_success,
                "stt_failure": self.stt_failure,
                "nlu_success": self.nlu_success,
                "nlu_failure": self.nlu_failure,
                "channel_errors": self.channel_errors,
                "escalations": self.escalations,
                "corrections": self.corrections,
                "payments": {
                    "success": self.payment_success,
                    "failure": self.payment_failure,
                    "timeout": self.payment_timeout,
                },
                "document_verification": {
                    "verified": self.doc_verified,
                    "mismatch": self.doc_mismatch,
                    "unreadable": self.doc_unreadable,
                },
                "status_distribution": dict(self.status_counts),
                "latency_ms": {"count": len(lats), "avg": avg, "p50": p50},
            }


_METRICS = MetricsStore()


def get_metrics() -> MetricsStore:
    return _METRICS


def timed_ms() -> float:
    return time.perf_counter() * 1000
