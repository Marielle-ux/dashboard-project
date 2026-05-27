"""
Excel / CSV file loader with automatic format detection.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".tsv"}


def load_file(
    file_path: str | Path,
    sheet_name: str | int = 0,
    header_row: int = 0,
) -> pd.DataFrame:
    """
    Load data from an Excel or CSV file.

    Parameters
    ----------
    file_path : str or Path
        Path to the file (xlsx, xls, csv, tsv).
    sheet_name : str or int
        For Excel files, which sheet to read. Ignored for CSV.
    header_row : int
        Row index (0-based) containing column headers.

    Returns
    -------
    pd.DataFrame
    """
    path = Path(file_path)
    if not path.exists():
        logger.error("File not found: %s", path)
        return pd.DataFrame()

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        logger.error("Unsupported file format: %s", ext)
        return pd.DataFrame()

    if ext in (".csv", ".tsv"):
        sep = "\t" if ext == ".tsv" else ","
        df = pd.read_csv(path, sep=sep, header=header_row)
    else:
        df = pd.read_excel(path, sheet_name=sheet_name, header=header_row)

    logger.info("Loaded %d rows from %s", len(df), path.name)
    return df


def load_uploaded_file(uploaded_file) -> pd.DataFrame:
    """
    Load a Streamlit UploadedFile object.

    Parameters
    ----------
    uploaded_file : streamlit.runtime.uploaded_file_manager.UploadedFile
        File uploaded via st.file_uploader.

    Returns
    -------
    pd.DataFrame
    """
    name = uploaded_file.name.lower()
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(uploaded_file, header=0)
    elif name.endswith(".csv"):
        df = pd.read_csv(uploaded_file, header=0)
    elif name.endswith(".tsv"):
        df = pd.read_csv(uploaded_file, sep="\t", header=0)
    else:
        logger.error("Unsupported uploaded file format: %s", name)
        return pd.DataFrame()

    logger.info("Loaded %d rows from uploaded file %s", len(df), uploaded_file.name)
    return df
