"""Per-recipient validation.

Request-shape problems (missing title, recipients not a list, ...) are rejected
by Pydantic with HTTP 422. The checks here are about the *data* in each row.
A row that fails them is stored as INVALID with readable reasons, while the
valid rows in the same request still get their certificates.
"""
import re
from dataclasses import dataclass, field

from email_validator import EmailNotValidError, validate_email

from app.schemas import RecipientIn

MAX_NAME_LENGTH = 100  # longer names do not fit the certificate layout
MAX_ACHIEVEMENT_LENGTH = 150
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class CheckedRecipient:
    row_number: int
    name: str
    email: str | None
    achievement: str | None
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _printable_with_standard_font(text: str) -> bool:
    # The certificate uses PDF standard fonts, which cover the Windows-1252
    # character set (English and most Western European names).
    try:
        text.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _clean(value: str | None) -> str:
    return " ".join((value or "").split())  # trim and collapse inner whitespace


def check_recipient(row_number: int, raw: RecipientIn) -> CheckedRecipient:
    name = _clean(raw.name)
    email = _clean(raw.email) or None
    achievement = _clean(raw.achievement) or None
    errors: list[str] = []

    if not name:
        errors.append("name is required")
    else:
        if len(name) > MAX_NAME_LENGTH:
            errors.append(f"name is longer than {MAX_NAME_LENGTH} characters")
        if _CONTROL_CHARS.search(name):
            errors.append("name contains control characters")
        if not any(ch.isalpha() for ch in name):
            errors.append("name must contain at least one letter")
        if not _printable_with_standard_font(name):
            errors.append("name contains characters the certificate font cannot print")

    if email is not None:
        try:
            email = validate_email(email, check_deliverability=False).normalized.lower()
        except EmailNotValidError as exc:
            errors.append(f"email is invalid: {exc}")

    if achievement is not None:
        if len(achievement) > MAX_ACHIEVEMENT_LENGTH:
            errors.append(f"achievement is longer than {MAX_ACHIEVEMENT_LENGTH} characters")
        elif not _printable_with_standard_font(achievement):
            errors.append("achievement contains characters the certificate font cannot print")

    return CheckedRecipient(row_number, name, email, achievement, errors)


def check_recipients(recipients: list[RecipientIn]) -> list[CheckedRecipient]:
    """Validate every row and flag repeats of an earlier valid row."""
    checked: list[CheckedRecipient] = []
    first_seen: dict[tuple[str, str | None], int] = {}

    for index, raw in enumerate(recipients, start=1):
        row = check_recipient(index, raw)
        if row.is_valid:
            key = (row.name.casefold(), row.email)
            if key in first_seen:
                row.errors.append(f"duplicate of row {first_seen[key]}")
            else:
                first_seen[key] = index
        checked.append(row)
    return checked
