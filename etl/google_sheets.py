"""
Google Sheets data loader.
Reads spreadsheet data via gspread and returns a pandas DataFrame.
Supports per-spreadsheet error handling and connection validation.
"""

from __future__ import annotations

import logging

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from config import settings

logger = logging.getLogger(__name__)


def _get_client() -> gspread.Client:
    cfg = settings.google_sheets
    creds = Credentials.from_service_account_file(
        cfg.credentials_file, scopes=cfg.scopes
    )
    return gspread.authorize(creds)


def check_connection_status() -> tuple[str, str]:
    """
    Validate Google Sheets credentials and API connectivity.

    Returns
    -------
    (status, detail) where status is one of:
        "Connected", "Invalid credentials", "API disabled",
        "Permission denied", "Connection error", "Not configured"
    """
    cfg = settings.google_sheets
    if not cfg.is_configured:
        return "Not configured", "Add google_credentials.json to enable"

    try:
        client = _get_client()
        # Try listing files to verify both auth and Drive API
        client.list_spreadsheet_files()
        return "Connected", cfg.service_account_email
    except gspread.exceptions.APIError as exc:
        msg = str(exc)
        if "has not been used" in msg or "is disabled" in msg:
            if "drive" in msg.lower():
                return "API disabled", "Enable Google Drive API in Cloud Console"
            return "API disabled", "Enable Google Sheets API in Cloud Console"
        if "403" in msg:
            return "Permission denied", msg
        return "API error", msg
    except ValueError as exc:
        return "Invalid credentials", str(exc)
    except FileNotFoundError:
        return "Invalid credentials", "Credentials file not found"
    except Exception as exc:
        return "Connection error", str(exc)


def check_spreadsheet_access(spreadsheet_name: str) -> tuple[str, str]:
    """
    Check if a specific spreadsheet is accessible.

    Returns
    -------
    (status, detail) where status is one of:
        "Connected", "Not found", "Permission denied", "API error"
    """
    try:
        client = _get_client()
        ss = client.open(spreadsheet_name)
        ws_count = len(ss.worksheets())
        return "Connected", f"{ws_count} worksheet(s)"
    except gspread.exceptions.SpreadsheetNotFound:
        return "Not found", (
            f"Spreadsheet '{spreadsheet_name}' not found. "
            f"Share it with {settings.google_sheets.service_account_email}"
        )
    except gspread.exceptions.APIError as exc:
        msg = str(exc)
        if "403" in msg:
            if "has not been used" in msg or "is disabled" in msg:
                return "API disabled", "Enable Google Drive API in Cloud Console"
            return "Permission denied", msg
        return "API error", msg
    except Exception as exc:
        return "Error", str(exc)


def load_sheet(
    spreadsheet_name: str,
    worksheet_name: str | None = None,
    header_row: int = 1,
) -> pd.DataFrame:
    """
    Load a worksheet from Google Sheets into a DataFrame.

    Parameters
    ----------
    spreadsheet_name : str
        The title of the Google Spreadsheet.
    worksheet_name : str, optional
        The title of the specific worksheet/tab. Defaults to the first sheet.
    header_row : int
        Row number (1-based) containing column headers.

    Returns
    -------
    pd.DataFrame
    """
    if not settings.google_sheets.is_configured:
        logger.warning(
            "Google Sheets credentials not found – returning empty DataFrame"
        )
        return pd.DataFrame()

    try:
        client = _get_client()
        spreadsheet = client.open(spreadsheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(
            "Spreadsheet '%s' not found. Share it with %s",
            spreadsheet_name,
            settings.google_sheets.service_account_email,
        )
        return pd.DataFrame()
    except gspread.exceptions.APIError as exc:
        logger.error("Google API error opening '%s': %s", spreadsheet_name, exc)
        return pd.DataFrame()
    except Exception as exc:
        logger.error("Error opening '%s': %s", spreadsheet_name, exc)
        return pd.DataFrame()

    try:
        if worksheet_name:
            worksheet = spreadsheet.worksheet(worksheet_name)
        else:
            worksheet = spreadsheet.sheet1
    except gspread.exceptions.WorksheetNotFound:
        logger.error(
            "Worksheet '%s' not found in '%s'", worksheet_name, spreadsheet_name
        )
        return pd.DataFrame()

    records = worksheet.get_all_values()
    if not records or len(records) < header_row:
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
    """
    Load multiple worksheets from a single spreadsheet.

    Parameters
    ----------
    spreadsheet_name : str
        The title of the Google Spreadsheet.
    worksheet_names : list[str], optional
        Specific worksheets to load. If None, loads all worksheets.

    Returns
    -------
    dict mapping worksheet name -> DataFrame
    """
    if not settings.google_sheets.is_configured:
        logger.warning(
            "Google Sheets credentials not found – returning empty dict"
        )
        return {}

    try:
        client = _get_client()
        spreadsheet = client.open(spreadsheet_name)
    except gspread.exceptions.SpreadsheetNotFound:
        logger.error(
            "Spreadsheet '%s' not found. Share it with %s",
            spreadsheet_name,
            settings.google_sheets.service_account_email,
        )
        return {}
    except gspread.exceptions.APIError as exc:
        logger.error("Google API error opening '%s': %s", spreadsheet_name, exc)
        return {}
    except Exception as exc:
        logger.error("Error opening '%s': %s", spreadsheet_name, exc)
        return {}

    if worksheet_names is None:
        worksheets = spreadsheet.worksheets()
    else:
        worksheets = []
        for name in worksheet_names:
            try:
                worksheets.append(spreadsheet.worksheet(name))
            except gspread.exceptions.WorksheetNotFound:
                logger.error(
                    "Worksheet '%s' not found in '%s'", name, spreadsheet_name
                )

    result: dict[str, pd.DataFrame] = {}
    for ws in worksheets:
        records = ws.get_all_values()
        if records and len(records) > 1:
            headers = records[0]
            data = records[1:]
            df = pd.DataFrame(data, columns=headers)
            df.replace("", pd.NA, inplace=True)
            result[ws.title] = df

    return result


def load_all_configured_spreadsheets() -> list[pd.DataFrame]:
    """
    Load data from all spreadsheets listed in GOOGLE_SPREADSHEET_NAMES.

    Each spreadsheet's first worksheet is loaded. Adds a 'spreadsheet_name'
    column for attribution.

    Returns
    -------
    list[pd.DataFrame] — one per successfully loaded spreadsheet.
    """
    cfg = settings.google_sheets
    if not cfg.is_configured or not cfg.spreadsheet_names:
        return []

    dfs: list[pd.DataFrame] = []
    for name in cfg.spreadsheet_names:
        logger.info("Loading Google Sheet: %s", name)
        sheet_df = load_sheet(name)
        if not sheet_df.empty:
            sheet_df["spreadsheet_name"] = name
            if "source" not in sheet_df.columns:
                sheet_df["source"] = "google_sheets"
            dfs.append(sheet_df)
            logger.info("  -> %d rows loaded from '%s'", len(sheet_df), name)
        else:
            logger.warning("  -> No data from '%s'", name)

    return dfs
