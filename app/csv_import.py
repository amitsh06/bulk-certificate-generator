"""Turning an uploaded CSV file into recipients.

Expected header: name,email,achievement (email and achievement are optional).
"""
import csv
import io

from app.schemas import RecipientIn

MAX_CSV_BYTES = 2 * 1024 * 1024
KNOWN_COLUMNS = {"name", "email", "achievement"}


class CsvFormatError(ValueError):
    pass


def parse_recipients_csv(content: bytes) -> list[RecipientIn]:
    if len(content) > MAX_CSV_BYTES:
        raise CsvFormatError("CSV file is larger than 2 MB")
    try:
        text = content.decode("utf-8-sig")  # tolerate the BOM Excel adds
    except UnicodeDecodeError as exc:
        raise CsvFormatError("CSV file must be UTF-8 encoded") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CsvFormatError("CSV file is empty")
    columns = {name.strip().lower(): name for name in reader.fieldnames if name}
    if "name" not in columns:
        raise CsvFormatError("CSV header must include a 'name' column")

    recipients = []
    for row in reader:
        values = {key: row.get(original) for key, original in columns.items() if key in KNOWN_COLUMNS}
        if not any((v or "").strip() for v in values.values()):
            continue  # skip completely blank lines
        recipients.append(RecipientIn(**values))
    if not recipients:
        raise CsvFormatError("CSV file has no recipient rows")
    return recipients
