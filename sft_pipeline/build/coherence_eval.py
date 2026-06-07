"""SFT 데이터셋 정합성 평가 — 정량 지표 + 정성 루브릭(각 점수에 근거 부착).

두 스킬의 방법론을 코드로 옮긴다:
- sft-dataset-coherence: 기계적 정합성(중복 제거·길이 분포·label 커버리지·round-trip)
- evaluating-plan-coherence: 플랜 논리성 3단 게이트(구문/구조 S1~S5/의미 M1~M4)

정량 지표는 결정론적으로 자동 산출하고(각 지표 dict 에 value/count/rationale),
정성 지표(M2~M4)는 사람·LLM 판정이 필요하므로 루브릭 정의 + 채점용 샘플을 리포트에
남긴다(M1 기계적 분해는 자동 근사 지표로 함께 제공). 사유 없는 점수는 만들지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from datetime import date
from pathlib import Path

from sft_pipeline.build.plan_schemas import check_plan_consistency, parse_plan
from sft_pipeline.build.validate_dataset import PLAN_PROVENANCES, _horizon_days

# M1(분배 합리성)의 자동 근사: 제목이 'N단원/N일차/N장/N주차/N강' 식 기계적 열거인지.
# (evaluating-plan-coherence M1, validate 의 단조분해 정책과 동일 취지)
_MECHANICAL_RE = re.compile(r"\d+\s*(단원|일차|장|주차|강)")


def _provenance(sample: dict) -> str:
    return (sample.get("meta") or {}).get("provenance", "?")


def _assistant(sample: dict) -> str:
    msgs = sample.get("messages") or []
    return str(msgs[-1]["content"]) if msgs else ""


def _canonical(sample: dict) -> str:
    return json.dumps(sample.get("messages"), ensure_ascii=False, sort_keys=True)


def _parse_plan_or_none(content: str):
    try:
        return parse_plan(content)
    except Exception:  # noqa: BLE001 - 파싱 실패 = 구문 게이트 FAIL
        return None


def _titles(plan) -> list[str]:
    return [t.title for t in plan.todos] + [t.title for t in plan.calendar_events]


def _mechanical_fraction(plan) -> float:
    titles = _titles(plan)
    if not titles:
        return 0.0
    hits = sum(1 for t in titles if _MECHANICAL_RE.search(t))
    return hits / len(titles)


def _has_dup_item(plan) -> bool:
    titles = _titles(plan)
    return len(titles) != len(set(titles))


def _metric(value, rationale: str, count=None) -> dict:
    node = {"value": value, "rationale": rationale}
    if count is not None:
        node["count"] = count
    return node


def _rate(num: int, den: int) -> float | None:
    return (num / den) if den else None


_RUBRIC = {
    "M1": {
        "차원": "분배 합리성",
        "5점기준": "'1단원,2단원' 기계적 균등이 아닌 난이도·맥락 반영 배분",
        "채점": "자동 근사 제공(gate3_M1_mechanical_rate). 최종 점수는 사람/LLM 판정",
        "출처": "evaluating-plan-coherence",
    },
    "M2": {
        "차원": "시간 현실성",
        "5점기준": "항목당 소요 시간 추정 현실적, 버퍼 존재",
        "채점": "사람/LLM 판정 (자동화 불가)",
        "출처": "evaluating-plan-coherence",
    },
    "M3": {
        "차원": "순서 논리",
        "5점기준": "선행→후행 의존 준수(복습은 학습 후 등)",
        "채점": "사람/LLM 판정",
        "출처": "evaluating-plan-coherence",
    },
    "M4": {
        "차원": "완결성(실현가능성)",
        "5점기준": "이 플랜대로 하면 목표가 실제로 달성됨",
        "채점": "사람/LLM 판정 (구조 게이트 통과가 전제)",
        "출처": "evaluating-plan-coherence",
    },
}


def _qualitative(samples: list[dict], per_prov: int = 3) -> dict:
    """Gate3(M1~M4) 정성 채점용 루브릭 + provenance별 대표 샘플(근거 인용 대상)."""
    picks: list[dict] = []
    by_prov: Counter = Counter()
    for s in samples:
        p = _provenance(s)
        if by_prov[p] < per_prov:
            by_prov[p] += 1
            picks.append(
                {
                    "provenance": p,
                    "user": (s.get("messages") or [{}])[0].get("content", "")[:200],
                    "assistant": _assistant(s)[:400],
                    "M1": None,
                    "M2": None,
                    "M3": None,
                    "M4": None,
                    "근거": "",
                }
            )
    return {
        "rubric": _RUBRIC,
        "note": "M2~M4 는 자동화 불가 — samples_for_review 를 출력 계약(위반/근거 인용)에 따라 사람/LLM 이 1~5점 채점. M1 은 자동 근사(mechanical_rate) 병행.",
        "samples_for_review": picks,
    }


def eval_dataset(samples: list[dict]) -> dict:
    n = len(samples)
    by_prov = dict(Counter(_provenance(s) for s in samples))

    # --- 기계적 정합성(sft-dataset-coherence) ---
    keys = [_canonical(s) for s in samples]
    dup_count = n - len(set(keys))
    empty_count = sum(1 for s in samples if not _assistant(s).strip())
    lens = [len(_assistant(s)) for s in samples] or [0]
    lens_sorted = sorted(lens)

    # --- 플랜 논리성(evaluating-plan-coherence) ---
    plan_samples = [s for s in samples if _provenance(s) in PLAN_PROVENANCES]
    n_plan = len(plan_samples)
    parsed = [(s, _parse_plan_or_none(_assistant(s))) for s in plan_samples]
    syntax_ok = [s for s, p in parsed if p is not None]
    parseable = [(s, p) for s, p in parsed if p is not None]

    s1_dup = 0
    s2_viol = 0
    m1_mech = 0
    structural_pass = 0
    for s, plan in parseable:
        meta = s.get("meta") or {}
        dup = _has_dup_item(plan)
        # S2: 시간 논리(날짜 범위·C5). 단조분해 사유는 M1 으로 분리.
        today_raw = meta.get("today")
        try:
            today = date.fromisoformat(str(today_raw)) if today_raw else None
        except ValueError:
            today = None
        if today is None:
            s2 = True
        else:
            errs = check_plan_consistency(plan, today=today, horizon_days=_horizon_days(meta))
            s2 = any("단조 분해" not in e for e in errs)
        mech = _mechanical_fraction(plan) > 0.5
        s1_dup += int(dup)
        s2_viol += int(s2)
        m1_mech += int(mech)
        if not dup and not s2 and not mech:
            structural_pass += 1

    # --- distractor 누수(네거티브가 플랜을 뱉으면 안 됨) ---
    distractors = [s for s in samples if _provenance(s) == "distractor"]
    leak = sum(1 for s in distractors if _parse_plan_or_none(_assistant(s)) is not None)

    quantitative = {
        "exact_duplicate_rate": _metric(
            _rate(dup_count, n),
            "messages 정규화 후 완전 중복 비율. sft-dataset-coherence: exact dedup(중복은 과적합·평가오염). 0 권장.",
            count=dup_count,
        ),
        "empty_assistant_rate": _metric(
            _rate(empty_count, n),
            "assistant 출력이 빈/공백인 비율. label 0개 샘플은 NaN loss 위험 → 0 이어야 함.",
            count=empty_count,
        ),
        "assistant_char_len": {
            "min": lens_sorted[0],
            "median": int(statistics.median(lens_sorted)),
            "p95": lens_sorted[min(len(lens_sorted) - 1, int(0.95 * (len(lens_sorted) - 1)))],
            "max": lens_sorted[-1],
            "rationale": "assistant 길이 분포. 학습 전 max_len 초과분 drop 판단 근거(잘린 응답 학습 방지).",
        },
        "plan": {
            "n": n_plan,
            "gate1_syntax_pass_rate": _metric(
                _rate(len(syntax_ok), n_plan),
                "플랜 출력이 유효 JSON+PlanOutput 스키마로 파싱되는 비율(Gate1 구문). 1.0 권장.",
                count=len(syntax_ok),
            ),
            "gate2_S1_dup_item_rate": _metric(
                _rate(s1_dup, len(parseable)),
                "동일 항목이 todos·calendar 에 중복 배치된 비율(Gate2 S1 역할분리 위반). 0 권장.",
                count=s1_dup,
            ),
            "gate2_S2_time_logic_violation_rate": _metric(
                _rate(s2_viol, len(parseable)),
                "날짜가 horizon 밖이거나 C5(오늘=todos/미래=calendar) 위반 비율(Gate2 S2). 단조분해는 제외. 0 권장.",
                count=s2_viol,
            ),
            "gate3_M1_mechanical_rate": _metric(
                _rate(m1_mech, len(parseable)),
                "제목 과반이 'N단원/N일차' 식 기계적 열거인 비율(Gate3 M1 자동 근사). 낮을수록 좋음.",
                count=m1_mech,
            ),
            "auto_structural_pass_rate": _metric(
                _rate(structural_pass, len(parseable)),
                "구문 PASS & S1/S2 무위반 & 비기계적 비율. 최종 ACCEPT 는 여기에 의미평가(M2~M4)≥4.0 필요.",
                count=structural_pass,
            ),
        },
        "distractor": {
            "n": len(distractors),
            "leak_rate": _metric(
                _rate(leak, len(distractors)),
                "distractor(잡담·거절)인데 assistant 가 플랜 JSON 을 뱉은 비율(=경계 학습 오염). 0 이어야 함.",
                count=leak,
            ),
        },
    }

    return {
        "n_samples": n,
        "by_provenance": by_prov,
        "quantitative": quantitative,
        "qualitative": _qualitative(samples),
    }


def _load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _print_log(report: dict) -> None:
    q = report["quantitative"]
    print(f"[coherence] n={report['n_samples']} provenance={report['by_provenance']}")
    print(f"[coherence] 중복률={q['exact_duplicate_rate']['value']} 빈출력률={q['empty_assistant_rate']['value']}")
    p = q["plan"]
    print(
        f"[coherence][plan n={p['n']}] gate1구문={p['gate1_syntax_pass_rate']['value']} "
        f"S1중복={p['gate2_S1_dup_item_rate']['value']} S2시간={p['gate2_S2_time_logic_violation_rate']['value']} "
        f"M1기계적={p['gate3_M1_mechanical_rate']['value']} 구조PASS={p['auto_structural_pass_rate']['value']}"
    )
    d = q["distractor"]
    print(f"[coherence][distractor n={d['n']}] 누수율={d['leak_rate']['value']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SFT 데이터셋 정합성 평가(정량+정성 루브릭)")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", type=Path, default=None, help="JSON 리포트 경로")
    args = parser.parse_args()

    samples = _load_jsonl(args.in_path)
    report = eval_dataset(samples)
    _print_log(report)
    if args.out_path:
        args.out_path.parent.mkdir(parents=True, exist_ok=True)
        args.out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[coherence] report -> {args.out_path}")


if __name__ == "__main__":
    main()
