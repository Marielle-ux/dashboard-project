"""
Google Sheets data loader.
Reads spreadsheet data via gspread and returns a pandas DataFrame.
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

    client = _get_client()
    spreadsheet = client.open(spreadsheet_name)

    if worksheet_name:
        worksheet = spreadsheet.worksheet(worksheet_name)
    else:
        worksheet = spreadsheet.sheet1

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

    client = _get_client()
    spreadsheet = client.open(spreadsheet_name)

    if worksheet_names is None:
        worksheets = spreadsheet.worksheets()
    else:
        worksheets = [spreadsheet.worksheet(name) for name in worksheet_names]

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
