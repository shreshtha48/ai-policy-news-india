"""Polite HTTP: one session, retries with backoff, per-host minimum interval."""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)
UA = ("Mozilla/5.0 (compatible; ai-policy-news-india/0.1; research project; "
      "+https://github.com/shreshtha48/ai-policy-news-india)")

_session: requests.Session | None = None
_last_hit: dict[str, float] = {}
DEFAULT_INTERVAL = 1.5


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        # 429 is NOT retried automatically: for keyed APIs a retry burns quota.
        retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504],
                      allowed_methods=["GET"])
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        s.headers["User-Agent"] = UA
        _session = s
    return _session


def get(url: str, params: dict | None = None, min_interval: float = DEFAULT_INTERVAL,
        timeout: int = 25, headers: dict | None = None) -> requests.Response:
    host = urlparse(url).netloc
    wait = _last_hit.get(host, 0) + min_interval - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    try:
        return session().get(url, params=params, timeout=timeout, headers=headers)
    finally:
        _last_hit[host] = time.monotonic()
