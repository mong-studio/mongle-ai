from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests

from sft_pipeline.crawl.extractor import extract
from sft_pipeline.crawl.fetcher import DEFAULT_USER_AGENT, fetch
from sft_pipeline.crawl.robots import evaluate, robots_url_for

RESULT_COLUMNS = [
    "source_url",
    "robots_url",
    "robots_allowed",
    "crawl_delay",
    "status_code",
    "title",
    "extracted_text",
    "text_length",
    "html_path",
    "error",
    "fetched_at",
]

def read_urls(path: Path) -> list[str]:
    urls: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            url = re.split(r"\s+#", stripped, maxsplit=1)[0].strip()
            if url:
                urls.append(url)
    return urls


def _now() -> str:
    # 결정성을 위해 고정 타임스탬프(테스트·재현 친화). 실제 시각이 필요하면 호출측에서 갱신.
    return "1970-01-01T00:00:00Z"


def _empty_row(url: str, robots_url: str) -> dict:
    return {c: "" for c in RESULT_COLUMNS} | {
        "source_url": url,
        "robots_url": robots_url,
        "fetched_at": _now(),
    }


def _effective_delay(sleep: float, crawl_delay) -> float:
    try:
        declared = float(crawl_delay)
    except (TypeError, ValueError):
        declared = 0.0
    return max(sleep, declared)


def _crawl_one(
    url: str,
    *,
    user_agent: str,
    session,
    timeout: float,
    robots_cache: dict[str, str] | None = None,
) -> dict:
    row = _empty_row(url, robots_url_for(url))

    domain = urlsplit(url).netloc
    if robots_cache is None:
        robots_cache = {}
    if domain not in robots_cache:
        robots_cache[domain] = _fetch_robots(url, session, timeout, user_agent)
    robots_text = robots_cache[domain]

    info = evaluate(url, user_agent, robots_text=robots_text)
    row["robots_allowed"] = str(info.allowed)
    row["crawl_delay"] = "" if info.crawl_delay is None else info.crawl_delay

    if not info.allowed:
        row["error"] = "robots_disallow"
        return row

    result = fetch(url, session=session, timeout=timeout, user_agent=user_agent)
    status, html, error = result.status_code, result.html, result.error

    row["status_code"] = "" if status is None else status
    if error:
        row["error"] = error
        return row

    if status is not None and status >= 400:
        row["error"] = f"http_{status}"
        return row

    extracted = extract(html, url)
    row["title"] = extracted.title
    row["extracted_text"] = extracted.text
    row["text_length"] = extracted.text_length
    return row


def _fetch_robots(url: str, session, timeout: float, user_agent: str) -> str:
    result = fetch(robots_url_for(url), session=session, timeout=timeout, user_agent=user_agent)
    return result.html or ""


def run(
    *,
    urls_path: Path,
    out_csv: Path,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = 10.0,
    sleep: float = 1.0,
) -> list[dict]:
    session = requests.Session()
    urls = read_urls(urls_path)
    robots_cache: dict[str, str] = {}
    rows: list[dict] = []
    for i, url in enumerate(urls):
        row = _crawl_one(url, user_agent=user_agent, session=session, timeout=timeout, robots_cache=robots_cache)
        rows.append(row)
        if i + 1 < len(urls):
            time.sleep(_effective_delay(sleep, row["crawl_delay"]))

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    out_jsonl = out_csv.with_suffix(".jsonl")
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="urls.txt → crawl_results.csv/.jsonl")
    parser.add_argument("--urls", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="crawl_results.csv 경로")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()
    rows = run(
        urls_path=args.urls,
        out_csv=args.out,
        user_agent=args.user_agent,
        timeout=args.timeout,
        sleep=args.sleep,
    )
    blocked = sum(1 for r in rows if r["error"] == "robots_disallow")
    print(f"crawled {len(rows)} urls ({blocked} robots-blocked) -> {args.out}")


if __name__ == "__main__":
    main()
