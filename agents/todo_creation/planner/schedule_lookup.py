"""시험일 해석 훅 — 공식 사이트에서 시험일(deadline)을 가져온다 (설계서 §3.6).

원칙: SFT=구조(안정), 런타임 조회=사실(휘발성). 시험일은 매년 바뀌어 SFT 에 넣으면 stale →
런타임에 공식 사이트에서 가져온다. 모델-결정 tool-call 이 아니라 **코드가** 조건 충족 시 부른다
(plan_kind=exam & 시험일 없음 & 공식 도메인 아는 시험). 실패·불확실 시 기존 follow_up 폴백.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Protocol

from agents.todo_creation.state import ParsedGoal

log = logging.getLogger(__name__)

# 공식 시험 일정 도메인(POC 시드). 키는 goal_tag/goal_text 에서 매칭할 키워드.
# include_domains 로 핀해 블로그 오답을 차단한다(Tavily basic 으로 충분).
OFFICIAL_DOMAINS: dict[str, list[str]] = {
    "정보처리기사": ["q-net.or.kr"],
    "정처기": ["q-net.or.kr"],
    "컴퓨터활용능력": ["license.korcham.net"],
    "컴활": ["license.korcham.net"],
    "토익": ["exam.toeic.co.kr", "toeic.co.kr"],
    "토익스피킹": ["exam.toeic.co.kr"],
    "토익라이팅": ["exam.toeic.co.kr"],
    "토플": ["toefl.ets.org"],
    "오픽": ["www.opic.or.kr"],
    "opic": ["www.opic.or.kr"],
    "토픽": ["www.topik.go.kr"],
    "topik": ["www.topik.go.kr"],
    "한국어능력시험": ["www.topik.go.kr"],
    "한국사능력검정": ["historyexam.go.kr"],
    "한능검": ["historyexam.go.kr"],
    "sqld": ["www.dataq.or.kr"],
    "adsp": ["www.dataq.or.kr"],
    "빅데이터분석기사": ["www.dataq.or.kr"],
    "정보보안기사": ["q-net.or.kr"],
    "사회조사분석사": ["q-net.or.kr"],
    "워드프로세서": ["license.korcham.net"],
    "itq": ["license.kpc.or.kr"],
    "전산세무": ["license.kacpta.or.kr"],
    "전산회계": ["license.kacpta.or.kr"],
}


class ExamScheduleLookupPort(Protocol):
    """공식 출처에서 다음 시험일을 가져온다. 못 찾으면 None(되묻기 폴백)."""

    async def next_exam_date(
        self, *, exam_name: str, official_domains: list[str], today: date
    ) -> date | None: ...


def _match_exam(parsed_goal: ParsedGoal) -> tuple[str, list[str]] | None:
    """goal_tag/goal_text 에서 공식 도메인 아는 시험을 찾는다."""
    hay = (
        f"{parsed_goal.get('goal_tag', '')} {parsed_goal.get('goal_text', '')}"
        .replace(" ", "")
        .lower()  # 영문 키(opic/sqld 등) 대소문자 무관 매칭. 한글은 영향 없음.
    )
    for keyword, domains in OFFICIAL_DOMAINS.items():
        if keyword.lower() in hay:
            return keyword, domains
    return None


_DATE_PATTERNS = (
    re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"),
    re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
)
_MONTHDAY = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def parse_future_date(text: str, *, today: date) -> date | None:
    """텍스트에서 today 이후의 가장 이른 날짜를 뽑는다. 없으면 None.

    'YYYY-MM-DD', 'YYYY년 M월 D일', 'M월 D일'(연도 생략 시 올해/내년 추론) 지원.
    """
    candidates: list[date] = []
    for pat in _DATE_PATTERNS:
        for y, m, d in pat.findall(text):
            _try_add(candidates, int(y), int(m), int(d))
    for m, d in _MONTHDAY.findall(text):
        # 연도 생략: 올해로 보되 이미 지났으면 내년.
        for year in (today.year, today.year + 1):
            cand = _safe_date(year, int(m), int(d))
            if cand and cand > today:
                candidates.append(cand)
                break
    future = sorted(c for c in candidates if c > today)
    return future[0] if future else None


def _try_add(out: list[date], y: int, m: int, d: int) -> None:
    cand = _safe_date(y, m, d)
    if cand:
        out.append(cand)


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


async def resolve_exam_deadline(
    parsed_goal: ParsedGoal,
    *,
    today: date,
    lookup: ExamScheduleLookupPort | None,
) -> bool:
    """시험일 미상 + 알려진 시험이면 lookup 으로 deadline 을 채운다.

    채웠으면 True(되묻기 생략), 아니면 False(기존 follow_up 폴백). fail-open: lookup 예외·
    None·과거 날짜는 모두 False 로 안전하게 흘린다(잘못된 날짜보다 되묻기가 낫다).
    """
    if (
        lookup is None
        or parsed_goal.get("plan_kind") != "exam"
        or parsed_goal.get("deadline")
    ):
        return False
    matched = _match_exam(parsed_goal)
    if matched is None:
        return False
    name, domains = matched
    try:
        resolved = await lookup.next_exam_date(
            exam_name=name, official_domains=domains, today=today
        )
    except Exception as err:  # noqa: BLE001 - fail-open: 어떤 실패도 되묻기로 폴백
        log.warning("exam schedule lookup failed for %s: %s", name, err)
        return False
    if resolved and resolved > today:
        parsed_goal["deadline"] = resolved
        return True
    return False
