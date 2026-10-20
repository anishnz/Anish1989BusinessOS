"""
Small, safe helpers for CSV import and export.

- Imports read UTF-8 (Excel's "CSV UTF-8" too), with a size and row limit.
- Exports protect against "CSV injection": a cell starting with = + - @ or a
  tab is prefixed with ' so spreadsheet programs do not run it as a formula.
"""
from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.http import HttpResponse

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
TRUE_WORDS = {"1", "true", "yes", "y"}
FALSE_WORDS = {"0", "false", "no", "n"}
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


class RowError(Exception):
    pass


def read_rows(upload, *, required: set[str], allowed: set[str]) -> list[dict]:
    """Read an uploaded CSV into a list of {header: value} dicts (headers lower-case)."""
    if upload is None:
        raise ValidationError("Choose a CSV file to upload.")
    if upload.size > MAX_BYTES:
        raise ValidationError("The file is too big (the limit is 2 MB).")
    raw = upload.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("The file must be saved as CSV UTF-8.") from None
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or []) if h is not None]
    missing = required - set(headers)
    if missing:
        raise ValidationError(f"Missing column(s): {', '.join(sorted(missing))}.")
    unknown = set(headers) - allowed
    if unknown:
        raise ValidationError(f"Unknown column(s): {', '.join(sorted(unknown))}. Allowed: {', '.join(sorted(allowed))}.")
    reader.fieldnames = headers
    rows = []
    for row in reader:
        if None in row:  # more cells than headers
            row.pop(None)
        cleaned = {k: _unprotect((v or "").strip()) for k, v in row.items() if k}
        if any(cleaned.values()):
            rows.append(cleaned)
        if len(rows) > MAX_ROWS:
            raise ValidationError(f"Too many rows (the limit is {MAX_ROWS}). Split the file and import it in parts.")
    if not rows:
        raise ValidationError("The file has no rows.")
    return rows


def _unprotect(value: str) -> str:
    """Undo safe_cell's ' prefix, so an exported file can be imported again."""
    return value[1:] if len(value) > 1 and value[0] == "'" and value[1] in FORMULA_START else value


def parse_bool(value: str, *, default: bool) -> bool:
    value = (value or "").strip().lower()
    if not value:
        return default
    if value in TRUE_WORDS:
        return True
    if value in FALSE_WORDS:
        return False
    raise RowError(f"'{value}' should be yes or no.")


def parse_decimal(value: str, *, label: str, required: bool = False) -> Decimal | None:
    value = (value or "").strip().replace("$", "").replace(",", "").replace("NZ", "")
    if not value:
        if required:
            raise RowError(f"{label} is required.")
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise RowError(f"{label} '{value}' is not a number.") from None
    if not number.is_finite():
        raise RowError(f"{label} '{value}' is not a number.")
    return number


def safe_cell(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def csv_response(filename: str, headers: list[str], rows) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # lets Excel read UTF-8 (for example Nepali names) correctly
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return response
