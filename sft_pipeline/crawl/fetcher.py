from __future__ import annotations

from dataclasses import dataclass

import requests

DEFAULT_USER_AGENT = "mongle-sft-crawler/0.1 (+research; respects robots.txt)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int | None
    html: str | None
    error: str | None


def fetch(
    url: str,
    *,
    session=None,
    timeout: float = 10.0,
    user_agent: str = DEFAULT_USER_AGENT,
) -> FetchResult:
    sess = session or requests.Session()
    try:
        resp = sess.get(url, timeout=timeout, headers={"User-Agent": user_agent})
        return FetchResult(url, resp.status_code, resp.text, None)
    except Exception as exc:
        return FetchResult(url, None, None, f"{type(exc).__name__}: {exc}")
