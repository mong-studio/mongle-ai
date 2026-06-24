"""크롤 본문 → 일상 raw_daily 필드(GPT-4o 추출 전용, 구조 타깃 아님).

GPT-4o 는 비정형 후기에서 features 를 뽑고 광고/협찬을 거른다(§4.6).
구조 JSON 최종 타깃은 하류 빌더의 코드 결정론. 라이브 호출은 키 있을 때만.
"""
from __future__ import annotations

import json
import logging

from sft_pipeline.build.lib.rephrase import make_client

log = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.5

EXTRACT_SYSTEM = """
너는 한국어 생활/후기 글에서 '실제 실행한 계획'의 특징만 뽑아내는 추출기다.
글에 실제로 적힌 내용만 추출하고, 없는 값은 빈 문자열로 둔다(추측·창작 금지).
광고/협찬/체험단 글은 ad=true 로 표시한다.

[출력 규칙]
- 반드시 JSON 객체 하나만 출력한다. 마크다운·설명 금지.
- 스키마:
{
  "plan_kind": "routine|vague_goal|lifestyle|exam 또는 빈문자열",
  "goal_text": "글쓴이의 목표 요약",
  "activity": "핵심 활동(단일)",
  "domains": "운동;학습 처럼 세미콜론 구분",
  "cadence": "주3회 / 월수금 / 매일 등 빈도(원문 표현)",
  "time_of_day": "아침|오전|점심|오후|저녁|밤 또는 빈문자열",
  "horizon": "한 달 / 4주 등 기간(원문 표현)",
  "trigger": "계획을 시작한 계기",
  "real_breakdown": "실제 활동을 '활동|빈도|시간대'로, 여러 개는 세미콜론 구분. 준비/점검/정리 같은 잡무는 넣지 마라.",
  "confidence": 0.0~1.0,
  "ad": true | false
}
"""


def build_client_from_env():
    return make_client()


def _user(text: str) -> str:
    return f"다음 글에서 특징을 추출해라:\n{text}"


def extract_daily_features(
    text: str,
    *,
    source_url: str,
    source_type: str,
    client=None,
    model: str = "gpt-4o",
    temperature: float = 0.0,
) -> dict | None:
    if client is None:
        return None
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": _user(text)},
            ],
            temperature=temperature,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as exc:  # noqa: BLE001 - 추출 실패는 그 케이스를 드롭(품질 게이트)
        log.warning("일상 추출 실패(드롭): %s", exc)
        return None

    if data.get("ad") is True:
        return None
    try:
        if float(data.get("confidence", 0)) < _MIN_CONFIDENCE:
            return None
    except (TypeError, ValueError):
        return None

    return {
        "source_url": source_url,
        "source_type": source_type,
        "plan_kind": data.get("plan_kind", ""),
        "goal_text": data.get("goal_text", ""),
        "activity": data.get("activity", ""),
        "domains": data.get("domains", ""),
        "cadence": data.get("cadence", ""),
        "time_of_day": data.get("time_of_day", ""),
        "horizon": data.get("horizon", ""),
        "trigger": data.get("trigger", ""),
        "real_breakdown": data.get("real_breakdown", ""),
        "confidence": data.get("confidence", 0),
    }
