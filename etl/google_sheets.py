"""
Google Sheets data loader.

Reads spreadsheet data via *gspread* and returns pandas DataFrames.
Provides connection validation, per-spreadsheet access checks, and
partial-failure-tolerant bulk loading with automatic retry for
transient API errors.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2.0

StatusCode = Literal[
    "Connected",
    "Not configured",
    "API disabled",
    "Permission denied",
    "Not found",
    "Invalid credentials",
    "Quota exceeded",
    "Connection error",
    "API error",
]


@dataclass(frozen=True)
class ConnectionStatus:
    """Structured result from a connectivity or access check."""

    status: StatusCode
    detail: str
    ok: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "ok", self.status == "Connected")


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------
def _get_client() -> gspread.Client:
    """Authenticate and return a gspread client using service-account credentials.

    Supports two credential sources:
    1. Local JSON file (``google_credentials.json``)
    2. ``st.secrets["google_credentials"]`` dict (Streamlit Cloud)
    """
    cfg = settings.google_sheets
    info = cfg.credentials_info
    if info:
        creds = Credentials.from_service_account_info(info, scopes=cfg.scopes)
    else:
        creds = Credentials.from_service_account_file(
            cfg.credentials_file, scopes=cfg.scopes
        )
    return gspread.authorize(creds)


def _classify_api_error(exc: gspread.exceptions.APIError) -> tuple[StatusCode, str]:
    """Map a gspread APIError to a human-readable (status, detail) pair."""
    msg = str(exc)
    code = ""
    try:
        code = str(exc.response.status_code)
    except Exception:
        pass

    if "has not been used" in msg or "is disabled" in msg:
        api_hint = "Google Drive API" if "drive" in msg.lower() else "Google Sheets API"
        return "API disabled", f"Enable {api_hint} in Cloud Console"
    if code == "429" or "quota" in msg.lower() or "rate limit" in msg.lower():
        return "Quota exceeded", "API rate limit reached — try again later"
    if code == "403":
        return "Permission denied", msg
    return "API error", msg


def _is_retryable(exc: Exception) -> bool:
    """Return True if the error is transient and worth retrying."""
    if isinstance(exc, gspread.exceptions.APIError):
        try:
            status = exc.response.status_code
        except Exception:
            status = 0
        # 429 Too Many Requests, 500/502/503/504 server errors
        if status in (429, 500, 502, 503, 504):
            return True
        msg = str(exc).lower()
        return "quota" in msg or "rate limit" in msg
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    return False


def _retry(func, *args, label: str = "operation", **kwargs):
    """Execute *func* with exponential-backoff retry on transient failures."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if _is_retryable(exc) and attempt < _MAX_RETRIES:
                wait = _RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "%s: transient error (attempt %d/%d), retrying in %.1fs — %s",
                    label, attempt, _MAX_RETRIES, wait, exc,
                )
                time.sleep(wait)
            else:
                raise
    raise last_exc  # pragma: no cover


# ---------------------------------------------------------------------------
# Public API — connection checks
# ---------------------------------------------------------------------------
def check_connection_status() -> tuple[str, str]:
    """Validate Google Sheets credentials and API connectivity.

    Verifies that:
    1. The credentials file exists and is parseable.
    2. The service-account can authenticate with Google.
    3. The Google Drive API is enabled (required by gspread to list/open sheets).

    Returns
    -------
    tuple[str, str]
        ``(status, detail)`` — *status* is a human-readable code such as
        ``"Connected"``, ``"API disabled"``, ``"Invalid credentials"``, etc.
        *detail* gives additional context (e.g. the service-account email on
        success, or an actionable error message on failure).
    """
    cfg = settings.google_sheets
    if not cfg.is_configured:
        return "Not configured", "Add google_credentials.json to enable"

    def _probe() -> tuple[str, str]:
        client = _get_client()
        client.list_spreadsheet_files()
        return "Connected", cfg.service_account_email

    try:
        return _retry(_probe, label="check_connection_status")
    except gspread.exceptions.APIError as exc:
        status, detail = _classify_api_error(exc)
        logger.error("Google Sheets connection check failed: %s — %s", status, detail)
        return status, detail
    except ValueError as exc:
        logger.error("Invalid credentials file: %s", exc)
        return "Invalid credentials", str(exc)
    except FileNotFoundError:
        logger.error("Credentials file not found at %s", cfg.credentials_file)
        return "Invalid credentials", "Credentials file not found"
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.error("Network error during connection check: %s", exc)
        return "Connection error", f"Network error: {exc}"
    except Exception as exc:
        logger.error("Unexpected error during connection check: %s", exc)
        return "Connection error", str(exc)


def check_spreadsheet_access(spreadsheet_name: str) -> tuple[str, str]:
    """Check whether a specific spreadsheet is accessible.

    Attempts to open the spreadsheet by title and count its worksheets.
    Distinguishes between "not found" (the sheet doesn't exist or isn't
    shared with the service account) and API-level errors.

    Parameters
    ----------
    spreadsheet_name : str
        Exact title of the Google Spreadsheet.

    Returns
    -------
    tuple[str, str]
        ``(status, detail)`` — see :func:`check_connection_status` for the
        status vocabulary.
    """
    if not spreadsheet_name or not spreadsheet_name.strip():
        return "Not found", "Spreadsheet name is empty"

    sa_email = settings.google_sheets.service_account_email

    def _probe() -> tuple[str, str]:
        client = _get_client()
        ss = client.open(spreadsheet_name)
        ws_count = len(ss.worksheets())
        return "Connected", f"{ws_count} worksheet(s)"

    try:
        status, detail = _retry(
            _probe, label=f"check_spreadsheet_access({spreadsheet_name!r})"
        )
        logger.info("Spreadsheet '%s': %s (%s)", spreadsheet_name, status, detail)
        return status, detail
    except gspread.exceptions.SpreadsheetNotFound:
        detail = (
            f"'{spreadsheet_name}' not found. "
            f"Share it with {sa_email}"
        )
        logger.warning("Spreadsheet not found: %s", spreadsheet_name)
        return "Not found", detail
    except gspread.exceptions.APIError as exc:
        status, detail = _classify_api_error(exc)
        logger.error(
            "API error accessing '%s': %s — %s", spreadsheet_name, status, detail,
        )
        return status, detail
    except (ConnectionError, TimeoutError, OSError) as exc:
        logger.error("Network error accessing '%s': %s", spreadsheet_name, exc)
        return "Connection error", f"Network error: {exc}"
    except Exception as exc:
        logger.error("Unexpected error accessing '%s': %s", spreadsheet_name, exc)
        return "Connection error", str(exc)


# ---------------------------------------------------------------------------
# Public API — data loading
# ---------------------------------------------------------------------------
def load_sheet(
    spreadsheet_name: str,
    worksheet_name: str | None = None,
    header_row: int = 1,
) -> pd.DataFrame:
    """Load a single worksheet from Google Sheets into a DataFrame.

    Parameters
    ----------
    spreadsheet_name : str
        The title of the Google Spreadsheet.
    worksheet_name : str | None
        Title of the specific worksheet/tab. ``None`` loads the first sheet.
    header_row : int
        1-based row number containing column headers.

    Returns
    -------
    pd.DataFrame
        The worksheet contents, or an empty DataFrame on any error.
    """
    if not settings.google_sheets.is_configured:
        logger.warning("Google Sheets not configured — returning empty DataFrame")
        return pd.DataFrame()

    label = f"load_sheet({spreadsheet_name!r})"

    # Open spreadsheet (with retry)
    try:
        client = _retry(_get_client, label=label)
        spreadsheet = _retry(client.open, spreadsheet_name, label=label)
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(
            "%s: not found — share with %s",
            label, settings.google_sheets.service_account_email,
        )
        return pd.DataFrame()
    except gspread.exceptions.APIError as exc:
        status, detail = _classify_api_error(exc)
        logger.error("%s: %s — %s", label, status, detail)
        return pd.DataFrame()
    except Exception as exc:
        logger.error("%s: %s", label, exc)
        return pd.DataFrame()

    # Select worksheet
    try:
        if worksheet_name:
            worksheet = spreadsheet.worksheet(worksheet_name)
        else:
            worksheet = spreadsheet.sheet1
    except gspread.exceptions.WorksheetNotFound:
        logger.error(
            "%s: worksheet '%s' not found", label, worksheet_name,
        )
        return pd.DataFrame()

    # Read data (with retry for transient failures)
    try:
        records: list[list[str]] = _retry(
            worksheet.get_all_values, label=label,
        )
    except Exception as exc:
        logger.error("%s: failed to read cells — %s", label, exc)
        return pd.DataFrame()

    if not records or len(records) < header_row:
        logger.info("%s: no data rows (total rows: %d)", label, len(records))
        return pd.DataFrame()

    headers = records[header_row - 1]
    data = records[header_row:]
    df = pd.DataFrame(data, columns=headers)
    df.replace("", pd.NA, inplace=True)
    return df


def load_multiple_sheets(
    spreadsheet_name: str,
    worksheet_names: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Load multiple worksheets from a single spreadsheet.

    Parameters
    ----------
    spreadsheet_name : str
        Title of the Google Spreadsheet.
    worksheet_names : list[str] | None
        Specific worksheets to load. ``None`` loads all worksheets.

    Returns
    -------
    dict[str, pd.DataFrame]
        Mapping of worksheet title → DataFrame. Worksheets that fail to
        load are silently skipped (logged as warnings).
    """
    if not settings.google_sheets.is_configured:
        logger.warning("Google Sheets not configured — returning empty dict")
        return {}

    label = f"load_multiple_sheets({spreadsheet_name!r})"

    try:
        client = _retry(_get_client, label=label)
        spreadsheet = _retry(client.open, spreadsheet_name, label=label)
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(
            "%s: not found — share with %s",
            label, settings.google_sheets.service_account_email,
        )
        return {}
    except gspread.exceptions.APIError as exc:
        status, detail = _classify_api_error(exc)
        logger.error("%s: %s — %s", label, status, detail)
        return {}
    except Exception as exc:
        logger.error("%s: %s", label, exc)
        return {}

    if worksheet_names is None:
        worksheets = spreadsheet.worksheets()
    else:
        worksheets = []
        for name in worksheet_names:
            try:
                worksheets.append(spreadsheet.worksheet(name))
            except gspread.exceptions.WorksheetNotFound:
                logger.warning("%s: worksheet '%s' not found — skipping", label, name)

    result: dict[str, pd.DataFrame] = {}
    for ws in worksheets:
        try:
            records = _retry(ws.get_all_values, label=f"{label}[{ws.title}]")
        except Exception as exc:
            logger.warning(
                "%s: failed to read worksheet '%s' — %s", label, ws.title, exc,
            )
            continue
        if records and len(records) > 1:
            headers = records[0]
            data = records[1:]
            df = pd.DataFrame(data, columns=headers)
            df.replace("", pd.NA, inplace=True)
            result[ws.title] = df

    return result


def load_all_configured_spreadsheets() -> list[pd.DataFrame]:
    """Load data from every spreadsheet listed in ``GOOGLE_SPREADSHEET_NAMES``.

    Each spreadsheet's first worksheet is loaded using the header row
    specified by ``GOOGLE_HEADER_ROW``. A ``spreadsheet_name`` column is
    added for source attribution, and ``source`` is set to
    ``"google_sheets"`` if not already present.

    **Partial-failure tolerant**: if one spreadsheet fails (permissions,
    network, quota), the others are still loaded and returned. Errors are
    logged but never propagated.

    Returns
    -------
    list[pd.DataFrame]
        One DataFrame per successfully loaded spreadsheet. May be empty
        if no spreadsheets are configured or all fail.
    """
    cfg = settings.google_sheets
    if not cfg.is_configured:
        logger.info("Google Sheets not configured — skipping")
        return []
    if not cfg.spreadsheet_names:
        logger.info("No spreadsheet names configured — skipping")
        return []

    total = len(cfg.spreadsheet_names)
    logger.info(
        "Loading %d configured Google Sheet(s) (header_row=%d)",
        total, cfg.header_row,
    )

    dfs: list[pd.DataFrame] = []
    loaded = 0
    failed = 0

    for idx, name in enumerate(cfg.spreadsheet_names, start=1):
        logger.info("[%d/%d] Loading '%s' …", idx, total, name)
        try:
            sheet_df = load_sheet(name, header_row=cfg.header_row)
        except Exception as exc:
            # Defensive: load_sheet already handles errors, but guard anyway
            logger.error("[%d/%d] Unexpected error loading '%s': %s", idx, total, name, exc)
            failed += 1
            continue

        if sheet_df.empty:
            logger.warning("[%d/%d] No data returned from '%s'", idx, total, name)
            failed += 1
            continue

        sheet_df["spreadsheet_name"] = name
        if "source" not in sheet_df.columns:
            sheet_df["source"] = "google_sheets"

        dfs.append(sheet_df)
        loaded += 1
        logger.info("[%d/%d] Loaded %d rows from '%s'", idx, total, len(sheet_df), name)

    logger.info(
        "Google Sheets loading complete: %d/%d succeeded, %d failed",
        loaded, total, failed,
    )
    return dfs
