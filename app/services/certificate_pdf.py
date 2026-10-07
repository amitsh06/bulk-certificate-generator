"""The predefined certificate template, drawn with ReportLab.

There is exactly one design. Only the recipient-specific fields change.
"""
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)
NAVY = HexColor("#1F3A5F")
GOLD = HexColor("#B8892E")
GREY = HexColor("#555555")


@dataclass(frozen=True)
class CertificateData:
    recipient_name: str
    title: str
    issued_by: str
    issued_on: date
    certificate_number: str
    achievement: str | None = None


def _fit_font_size(text: str, font: str, max_size: float, min_size: float, max_width: float) -> float:
    """Largest size from max_size down to min_size at which the text fits the width.
    If it is still too wide at min_size, shrink exactly to fit so it never overflows."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    width = stringWidth(text, font, size)
    return size if width <= max_width else size * max_width / width


def _fit_lines(text: str, font: str, max_size: float, min_size: float, max_width: float) -> tuple[list[str], float]:
    """Fit text on one line, or split it into two balanced lines when one line
    would need a font smaller than min_size. Returns the lines and the font size."""
    if stringWidth(text, font, min_size) <= max_width or " " not in text:
        return [text], _fit_font_size(text, font, max_size, min_size, max_width)
    words = text.split()
    splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
    lines = list(min(splits, key=lambda pair: max(stringWidth(part, font, max_size) for part in pair)))
    size = min(_fit_font_size(line, font, max_size, min_size, max_width) for line in lines)
    return lines, size


def _centered(c: canvas.Canvas, text: str, y: float, font: str, size: float, color=NAVY) -> None:
    c.setFont(font, size)
    c.setFillColor(color)
    c.drawCentredString(PAGE_WIDTH / 2, y, text)


def render_certificate(output_path: Path, data: CertificateData) -> Path:
    """Write the certificate PDF to output_path.

    The file is written to a temporary name first and then renamed, so a crash
    halfway through never leaves a broken PDF behind under the real name.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".pdf.tmp")

    c = canvas.Canvas(str(tmp_path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    c.setTitle(f"Certificate - {data.recipient_name}")
    c.setAuthor(data.issued_by)
    text_width = PAGE_WIDTH - 160

    # Frame: thick navy border with a thin gold line inside it.
    c.setStrokeColor(NAVY)
    c.setLineWidth(6)
    c.rect(24, 24, PAGE_WIDTH - 48, PAGE_HEIGHT - 48)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.rect(36, 36, PAGE_WIDTH - 72, PAGE_HEIGHT - 72)

    _centered(c, "CERTIFICATE", PAGE_HEIGHT - 120, "Times-Bold", 44)
    _centered(c, "O F   C O M P L E T I O N", PAGE_HEIGHT - 148, "Helvetica", 14, GOLD)
    _centered(c, "This certificate is proudly presented to", PAGE_HEIGHT - 205, "Helvetica-Oblique", 14, GREY)

    # Recipient name: one big line, or two smaller lines for very long names.
    name_lines, name_size = _fit_lines(data.recipient_name, "Times-BoldItalic", 40, 24, text_width)
    name_baselines = [PAGE_HEIGHT - 262] if len(name_lines) == 1 else [PAGE_HEIGHT - 242, PAGE_HEIGHT - 270]
    for line, y in zip(name_lines, name_baselines):
        _centered(c, line, y, "Times-BoldItalic", name_size)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1)
    c.line(PAGE_WIDTH / 2 - 220, PAGE_HEIGHT - 282, PAGE_WIDTH / 2 + 220, PAGE_HEIGHT - 282)

    _centered(c, "for successfully completing", PAGE_HEIGHT - 310, "Helvetica", 14, GREY)
    title_lines, title_size = _fit_lines(data.title, "Helvetica-Bold", 22, 14, text_width)
    y = PAGE_HEIGHT - 342
    for line in title_lines:
        _centered(c, line, y, "Helvetica-Bold", title_size)
        y -= title_size + 6
    if data.achievement:
        achievement_size = _fit_font_size(data.achievement, "Helvetica-Oblique", 13, 9, text_width)
        _centered(c, data.achievement, y - 6, "Helvetica-Oblique", achievement_size, GREY)

    # Footer: date on the left, issuer on the right, certificate number in the middle.
    footer_y = 110
    for x_center, value, label in (
        (PAGE_WIDTH * 0.25, data.issued_on.strftime("%d %B %Y"), "Date of issue"),
        (PAGE_WIDTH * 0.75, data.issued_by, "Issued by"),
    ):
        value_size = _fit_font_size(value, "Helvetica-Bold", 13, 8, 220)
        c.setFont("Helvetica-Bold", value_size)
        c.setFillColor(NAVY)
        c.drawCentredString(x_center, footer_y + 8, value)
        c.setStrokeColor(NAVY)
        c.line(x_center - 110, footer_y, x_center + 110, footer_y)
        c.setFont("Helvetica", 10)
        c.setFillColor(GREY)
        c.drawCentredString(x_center, footer_y - 14, label)

    _centered(c, f"Certificate No. {data.certificate_number}", 60, "Helvetica", 9, GREY)

    c.showPage()
    c.save()
    os.replace(tmp_path, output_path)
    return output_path
