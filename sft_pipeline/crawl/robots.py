"""표준 urllib.robotparser 기반 robots 평가. 순수 함수(robots_text 주입)로 테스트 용이."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser


@dataclass(frozen=True)
class RobotsInfo:
    robots_url: str
    allowed: bool
    crawl_delay: float | None


def robots_url_for(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


def evaluate(url: str, user_agent: str, *, robots_text: str) -> RobotsInfo:
    parser = RobotFileParser()
    parser.parse((robots_text or "").splitlines())
    allowed = parser.can_fetch(user_agent, url)
    delay = parser.crawl_delay(user_agent)
    return RobotsInfo(
        robots_url=robots_url_for(url),
        allowed=allowed,
        crawl_delay=float(delay) if delay is not None else None,
    )
