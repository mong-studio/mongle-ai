from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from bs4 import BeautifulSoup

_CONFIG = Path(__file__).resolve().parent.parent / "config" / "extractors.yaml"


@lru_cache(maxsize=1)
def _config() -> dict:
    with open(_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass(frozen=True)
class Extracted:
    title: str
    text: str
    text_length: int
    used_selector: str


def _selectors_for(domain: str) -> list[str]:
    cfg = _config()
    # exact-domain keys must precede wildcard keys in extractors.yaml to take priority
    for key, selectors in cfg.items():
        if key in ("default", "min_length"):
            continue
        if key.startswith("*.") and domain.endswith(key[1:]):
            return selectors
        if key == domain:
            return selectors
    return cfg["default"]


def _title(soup: BeautifulSoup) -> str:
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else ""


def extract(html: str, url: str) -> Extracted:
    if not html:
        return Extracted("", "", 0, "fallback")
    soup = BeautifulSoup(html, "lxml")
    domain = urlsplit(url).netloc
    min_length = _config()["min_length"]
    title = _title(soup)

    for selector in _selectors_for(domain):
        node = soup.select_one(selector)
        if node:
            text = node.get_text(separator="\n", strip=True)
            if len(text) >= min_length:
                return Extracted(title, text, len(text), selector)

    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    text = "\n".join(filter(None, paragraphs))
    if not text:
        body = soup.find("body")
        text = body.get_text(separator="\n", strip=True) if body else ""
    return Extracted(title, text, len(text), "fallback")
