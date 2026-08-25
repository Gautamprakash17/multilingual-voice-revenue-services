"""Income Certificate PDF — deterministic POC layout, no third-party PDF stack.

Produces an uncompressed PDF 1.4 so field values remain searchable in the file
bytes. Helvetica/WinAnsi only: non-Latin characters are replaced, never invented.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models.application import Application

DEMO_DISCLAIMER = "DEMO / POC DOCUMENT - Not an official government certificate. No legal validity."
CERTIFICATE_TITLE = "Income Certificate"
ISSUED_CERTIFICATE_CODE = "ISSUED_CERTIFICATE"


class CertificateGenerationError(RuntimeError):
    """PDF bytes could not be produced. Caller must not mark the application ISSUED."""


def _winansi(value: str) -> str:
    return (value or "").encode("latin-1", "replace").decode("latin-1")


def _pdf_escape(value: str) -> str:
    return (
        _winansi(value)
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _form_text(form: dict[str, Any], key: str) -> str:
    raw = form.get(key)
    if raw is None:
        return ""
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    text = str(raw).strip()
    return text


def certificate_filename(application_id: str) -> str:
    return f"income-certificate-{application_id}.pdf"


def certificate_lines(app: Application, *, issued_at: datetime | None = None) -> list[str]:
    """Plain-text lines rendered into the PDF. Missing form fields stay blank (not invented)."""
    form = dict(app.form_data or {})
    when = issued_at or datetime.now(UTC)
    issue_date = when.date().isoformat()
    name = _form_text(form, "applicant_name")
    dob = _form_text(form, "date_of_birth")
    mobile = _form_text(form, "mobile_number")
    address = _form_text(form, "address")
    district = _form_text(form, "district")
    income = _form_text(form, "annual_income")
    source = _form_text(form, "income_source")
    return [
        "Revenue Voice Services - Demonstration",
        DEMO_DISCLAIMER,
        "",
        CERTIFICATE_TITLE,
        "",
        f"Application ID: {app.application_id}",
        f"Reference: {app.application_id}",
        f"Status: {app.processing_status or 'ISSUED'}",
        f"Issue date: {issue_date}",
        "",
        f"Applicant name: {name}" if name else "Applicant name:",
        f"Date of birth: {dob}" if dob else "Date of birth:",
        f"Mobile number: {mobile}" if mobile else "Mobile number:",
        f"Residential address: {address}" if address else "Residential address:",
        f"District: {district}" if district else "District:",
        f"Annual income: {income}" if income else "Annual income:",
        f"Income source: {source}" if source else "Income source:",
        "",
        "This document is generated for a hackathon proof of concept only.",
        "It must not be presented as a legally valid income certificate.",
    ]


def build_simple_pdf(lines: list[str], *, title: str) -> bytes:
    """Build a one-page Helvetica PDF. Content stream is uncompressed."""
    y = 760
    commands = ["BT", "/F1 11 Tf", f"72 {y} Td"]
    first = True
    for line in lines:
        text = _pdf_escape(line)
        size = 16 if line == CERTIFICATE_TITLE else 11
        leading = -22 if line == CERTIFICATE_TITLE else -16
        if first:
            commands.append(f"/F1 {size} Tf")
            commands.append(f"({text}) Tj")
            first = False
        else:
            commands.append(f"/F1 {size} Tf")
            commands.append(f"0 {leading} Td")
            commands.append(f"({text}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1")

    def obj(n: int, body: bytes) -> bytes:
        return b"%d 0 obj\n" % n + body + b"\nendobj\n"

    objects = [
        obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        obj(
            3,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        ),
        obj(4, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"),
        obj(5, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        obj(
            6,
            b"<< /Title (%s) /Subject (%s) /Creator (Revenue Voice Services POC) >>"
            % (
                _pdf_escape(title).encode("latin-1"),
                _pdf_escape(DEMO_DISCLAIMER).encode("latin-1"),
            ),
        ),
    ]

    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = []
    cursor = len(header)
    parts = [header]
    for chunk in objects:
        offsets.append(cursor)
        parts.append(chunk)
        cursor += len(chunk)
    xref_start = cursor
    xref = [b"xref\n0 7\n", b"0000000000 65535 f \n"]
    for off in offsets:
        xref.append(b"%010d 00000 n \n" % off)
    trailer = (
        b"trailer\n<< /Size 7 /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n" % xref_start
    )
    return b"".join(parts) + b"".join(xref) + trailer


def render_income_certificate_pdf(app: Application, *, issued_at: datetime | None = None) -> bytes:
    lines = certificate_lines(app, issued_at=issued_at)
    pdf = build_simple_pdf(lines, title=f"{CERTIFICATE_TITLE} {app.application_id}")
    if not pdf.startswith(b"%PDF-") or b"%%EOF" not in pdf:
        raise CertificateGenerationError("PDF renderer produced an unreadable file")
    if app.application_id.encode("ascii", "replace") not in pdf:
        raise CertificateGenerationError("PDF renderer omitted the Application ID")
    if b"DEMO / POC DOCUMENT" not in pdf:
        raise CertificateGenerationError("PDF renderer omitted the DEMO / POC disclaimer")
    return pdf
