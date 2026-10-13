"""Fetch a credit agreement exhibit and normalise it once."""

from __future__ import annotations

import re
from pathlib import Path

from backend.agreement.normalise import NormalisedAgreement, normalise
from backend.edgar.client import EdgarClient

EXHIBIT_URL = re.compile(r"^https://www\.sec\.gov/Archives/edgar/data/\d+/", re.I)


def fetch_agreement(
    url: str,
    *,
    client: EdgarClient | None = None,
    refresh: bool = False,
) -> NormalisedAgreement:
    """Fetch an EDGAR exhibit and return it as normalised text."""
    client = client or EdgarClient()
    raw = client.document(url, refresh=refresh)
    return normalise(raw, source_url=url)


def load_agreement(path: str | Path, *, source_url: str = "") -> NormalisedAgreement:
    """Normalise an exhibit already on disk, for offline runs and tests."""
    target = Path(path)
    raw = target.read_text(encoding="utf-8", errors="replace")
    return normalise(raw, source_url=source_url or target.as_uri())


def accession_from_url(url: str) -> str | None:
    """The accession number embedded in an EDGAR archive URL."""
    match = re.search(r"/(\d{10})(\d{2})(\d{6})/", url)
    if match:
        return match.group(1) + "-" + match.group(2) + "-" + match.group(3)
    match = re.search(r"/(\d{10}-\d{2}-\d{6})", url)
    return match.group(1) if match else None


def cik_from_url(url: str) -> str | None:
    match = re.search(r"/edgar/data/(\d+)/", url)
    return match.group(1) if match else None
