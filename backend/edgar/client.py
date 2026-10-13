"""EDGAR HTTP client: descriptive User-Agent, throttling, on-disk cache.

``data.sec.gov`` does not send CORS headers, so every fetch happens here in the
backend rather than in the browser. The SEC asks for a descriptive User-Agent
and a fair request rate; the cache means a quarterly rerun touches the network
once and then reproduces offline.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

SEC_RATE_LIMIT_PER_SECOND = 8  # the SEC publishes 10/s; stay under it
DEFAULT_USER_AGENT = "Headroom covenant research (dharmi.chauhan10@gmail.com)"
DEFAULT_CACHE_DIR = Path("data/cache")

#: Only these hosts are ever fetched. Anything else is a bug or a bad input.
ALLOWED_HOSTS = frozenset({"www.sec.gov", "data.sec.gov", "efts.sec.gov"})


class EdgarError(RuntimeError):
    """A fetch failed in a way the caller has to see."""


class OfflineError(EdgarError):
    """A document is not cached and the network is switched off."""


@dataclass(frozen=True)
class CachedResponse:
    url: str
    body: bytes
    content_type: str
    from_cache: bool

    def text(self) -> str:
        charset = "utf-8"
        match = re.search(r"charset=([\w-]+)", self.content_type or "", re.I)
        if match:
            charset = match.group(1)
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class _Throttle:
    """A process-wide minimum interval between SEC requests."""

    def __init__(self, per_second: int) -> None:
        self._interval = 1.0 / float(per_second)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            gap = self._interval - (now - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()


_THROTTLE = _Throttle(SEC_RATE_LIMIT_PER_SECOND)


def user_agent() -> str:
    return os.environ.get("HEADROOM_USER_AGENT", DEFAULT_USER_AGENT)


class EdgarClient:
    """Fetches EDGAR documents through a disk cache keyed by URL."""

    def __init__(
        self,
        *,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        allow_network: bool = True,
        timeout: float = 60.0,
        agent: str | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.allow_network = allow_network
        self.timeout = timeout
        self.agent = agent or user_agent()

    # -- cache ---------------------------------------------------------------

    def _paths(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]
        folder = self.cache_dir / digest[:2]
        return folder / (digest + ".body"), folder / (digest + ".meta.json")

    def cached(self, url: str) -> CachedResponse | None:
        body_path, meta_path = self._paths(url)
        if not body_path.exists() or not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return CachedResponse(
            url=url,
            body=body_path.read_bytes(),
            content_type=meta.get("content_type", ""),
            from_cache=True,
        )

    def _store(self, url: str, body: bytes, content_type: str) -> None:
        body_path, meta_path = self._paths(url)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(body)
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "content_type": content_type,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    # -- fetching ------------------------------------------------------------

    def get(self, url: str, *, refresh: bool = False) -> CachedResponse:
        """Fetch ``url``, from cache unless ``refresh`` is set."""
        host = httpx.URL(url).host
        if host not in ALLOWED_HOSTS:
            raise EdgarError("refusing to fetch a host outside EDGAR: " + str(host))

        if not refresh:
            hit = self.cached(url)
            if hit is not None:
                return hit
        if not self.allow_network:
            raise OfflineError("not cached and the network is off: " + url)

        _THROTTLE.wait()
        headers = {
            "User-Agent": self.agent,
            "Accept-Encoding": "gzip, deflate",
            "Host": host,
        }
        try:
            response = httpx.get(
                url, headers=headers, timeout=self.timeout, follow_redirects=True
            )
        except httpx.HTTPError as exc:
            raise EdgarError("fetch failed for " + url + ": " + str(exc)) from exc
        if response.status_code != 200:
            raise EdgarError(
                "EDGAR returned " + str(response.status_code) + " for " + url
            )
        body = response.content
        content_type = response.headers.get("content-type", "")
        self._store(url, body, content_type)
        return CachedResponse(url=url, body=body, content_type=content_type, from_cache=False)

    # -- endpoints -----------------------------------------------------------

    def company_facts(self, cik: str | int, *, refresh: bool = False) -> dict:
        """Every reported us-gaap fact for one company, in one call."""
        url = company_facts_url(cik)
        response = self.get(url, refresh=refresh)
        try:
            return json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise EdgarError("companyfacts for " + str(cik) + " is not JSON") from exc

    def document(self, url: str, *, refresh: bool = False) -> str:
        return self.get(url, refresh=refresh).text()


def normalise_cik(cik: str | int) -> str:
    """``320193``, ``"CIK0000320193"`` and ``"0000320193"`` all mean the same."""
    digits = re.sub(r"\D", "", str(cik))
    if not digits:
        raise ValueError("not a CIK: " + repr(cik))
    if len(digits) > 10:
        raise ValueError("a CIK has at most 10 digits: " + repr(cik))
    return digits.zfill(10)


def company_facts_url(cik: str | int) -> str:
    return "https://data.sec.gov/api/xbrl/companyfacts/CIK" + normalise_cik(cik) + ".json"


def submissions_url(cik: str | int) -> str:
    return "https://data.sec.gov/submissions/CIK" + normalise_cik(cik) + ".json"
