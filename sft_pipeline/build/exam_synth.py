"""시험 준비 플랜 합성(하이브리드) → exam_synth.jsonl.

exam-crawl(실제 블로그, 내부전용)은 수가 적어, 우리가 직접 합성한 시험 플랜을
보강한다. user 턴은 조건(시험종류·기간·목표 등)에서 결정론적으로 만들고, assistant
플랜은 LLM 이 작문하되 기존 검수 샘플(exam.jsonl)을 few-shot 그라운딩으로 쓴다.
정합성 검증(날짜범위·C5·단조분해 reject)에 실패하면 결정론적 템플릿으로 폴백한다.

provenance="exam-synth": 우리가 만든 합성 데이터라 외부 공개 가능(원문 인용 없음).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

from sft_pipeline.build.plan_schemas import (
    PlanOutput,
    PlanTask,
    _loads_lenient,
    _normalize_plan_dict,
    check_plan_consistency,
    dump_plan_for_training,
)
from sft_pipeline.latte.synthesize import make_local_client
from sft_pipeline.structure.exam_structure import concreteness_ratio, structure_for

log = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = 60.0

# 시험종류별 목표(난이도 스펙트럼). exam_types.yaml 의 표준코드와 일치.
EXAM_GOALS: dict[str, list[str]] = {
    "정보처리기사_필기": ["과목당 60점 합격", "평균 75점", "평균 85점 고득점"],
    "토익": ["700점", "800점", "900점"],
    "한국사능력검정시험": ["3급 합격", "2급", "1급"],
    "SQLD": ["60점 합격", "80점", "90점 고득점"],
    "컴활1급": ["필기 합격", "필기+실기 합격", "실기 고득점"],
    "컴활2급": ["필기 합격", "실기 합격", "필기+실기 합격"],
    "오픽": ["IM2", "IH", "AL"],
    "토플": ["80점", "90점", "100점 이상"],
    "JLPT": ["N3 합격", "N2 합격", "N1 합격"],
}
EXAM_TYPES: list[str] = list(EXAM_GOALS)

# 시드 다양화 축(시험종류와 무관하게 공통).
_DAYS_LEFT = [7, 14, 21, 30, 45, 60]
_DAILY_HOURS = [2, 3, 4]
_LEVELS = ["노베이스", "기초", "중급"]
_NOTES = ["직장 병행", "학업 병행", "전업 준비"]

_SYSTEM = (
    "너는 몽글마을의 현실적인 시험 준비 코치야. 주어진 조건에 맞춰 합격에 직결되는 "
    "구체적 전략 플랜을 JSON 으로 만들어줘. 각 항목 제목에는 시험의 실제 "
    "과목·파트·영역명을 넣어 공부 범위가 분명히 드러나게 해."
)

# LLM 플랜 채택 최소 구체성(구조 키워드 포함 title 비율). 미달 시 reject → 템플릿 폴백.
CONCRETENESS_MIN = 0.6

# LLM 시도 횟수. temperature>0 재샘플이라 1회 거부돼도 재시도 가치가 큼(전부 실패 시 폴백).
LLM_ATTEMPTS = 2


def _pick_even(seq: list[dict], k: int) -> list[dict]:
    """seq 에서 k 개를 균등 간격으로 결정론적으로 고른다."""
    if k >= len(seq):
        return list(seq)
    n = len(seq)
    return [seq[(i * n) // k] for i in range(k)]


def _seeds_for_type(exam_type: str, k: int) -> list[dict]:
    goals = EXAM_GOALS[exam_type]
    grid = [
        {
            "exam_type": exam_type,
            "goal": g,
            "days_left": d,
            "daily_hours": h,
            "level": lvl,
            "note": note,
        }
        for g in goals
        for d in _DAYS_LEFT
        for h in _DAILY_HOURS
        for lvl in _LEVELS
        for note in _NOTES
    ]
    return _pick_even(grid, k)


def build_seeds(total: int) -> list[dict]:
    """시험종류별로 균등하게(±1) 합쳐 총 total 개 시드를 만든다(결정론적)."""
    n = len(EXAM_TYPES)
    base, rem = divmod(total, n)
    out: list[dict] = []
    for i, exam_type in enumerate(EXAM_TYPES):
        k = base + (1 if i < rem else 0)
        out.extend(_seeds_for_type(exam_type, k))
    return out


def to_user_text(seed: dict, *, today: date) -> str:
    """조건 필드에서 사용자 요청 문장을 결정론적으로 만든다(실제 exam 포맷과 동일)."""
    return (
        "다음 조건에 맞는 단기 시험 준비 계획을 세워줘.\n\n"
        f"시험: {seed['exam_type']} / 남은 기간: D-{seed['days_left']} / "
        f"하루 가용: 하루 {seed['daily_hours']}시간 / 시작 수준: {seed['level']} / "
        f"목표: {seed['goal']} / 특이사항: {seed['note']} / 기준일(오늘): {today.isoformat()}"
    )


def _strip_item_count(section: str) -> str:
    """과목/파트명에서 '(20문항)' 류 문항수 주석만 떼고 명칭은 보존한다."""
    return re.sub(r"\s*\(\d+문항[^)]*\)", "", section).strip()


def _fit_title(section: str) -> str:
    """PlanTask.title 20자 제약에 맞춰 행동 접미사를 줄여가며 제목을 만든다."""
    for suffix in (" 집중 학습", " 학습", ""):
        title = f"{section}{suffix}"
        if len(title) <= 20:
            return title
    return section[:20]


def _fallback_plan(seed: dict, today: date) -> PlanOutput:
    """LLM 실패 시 쓰는 결정론적 폴백: 시험 구조(과목/파트) 기반 전략 템플릿."""
    horizon = int(seed["days_left"])
    structure = structure_for(seed["exam_type"]) or {}
    sections = [_strip_item_count(s) for s in structure.get("sections", [])]
    if not sections:  # 구조 미등록 시험은 일반 전략으로 안전 폴백
        sections = ["핵심 개념"]
    summary = (
        f"[{seed['exam_type']} · D-{horizon} · 하루 {seed['daily_hours']}시간] "
        f"시작 {seed['level']}, 목표 '{seed['goal']}'. "
        "전략: 과목·파트별 기출로 출제 감을 잡고, 약한 영역을 집중 보완한 뒤 모의고사로 점검하세요."
    )
    todos = [PlanTask(title=_fit_title(sections[0]), due_date=today)]
    rest = sections[1:]
    events = [
        PlanTask(
            title=_fit_title(sec),
            # 내일~D-(horizon-1) 사이에 균등 배치(결정론적), 마지막 날은 모의고사용으로 비움
            due_date=today + timedelta(days=1 + (i * (horizon - 2)) // max(len(rest) - 1, 1)),
        )
        for i, sec in enumerate(rest)
    ]
    events.append(
        PlanTask(title="실전 모의고사 점검", due_date=today + timedelta(days=horizon))
    )
    return PlanOutput(summary_text=summary, todos=todos, calendar_events=events)


def build_exam_prompt(seed: dict, *, today: date, exemplars: list[dict]) -> str:
    horizon = int(seed["days_left"])
    shots = ""
    for ex in exemplars:
        shots += f"\n[예시 플랜]\n{ex}\n"
    structure = structure_for(seed["exam_type"]) or {}
    section_lines = "\n".join(f"- {s}" for s in structure.get("sections", []))
    structure_block = (
        f"\n시험 구조(공식 출제기준):\n{section_lines}\n" if section_lines else ""
    )
    return (
        f"{to_user_text(seed, today=today)}\n"
        f"{structure_block}\n"
        "요구사항:\n"
        f"1) plan.todos 에는 오늘({today.isoformat()}) 할 일만, "
        f"plan.calendar_events 에는 내일부터 D-{horizon}({(today + timedelta(days=horizon)).isoformat()}) "
        "이내 일만 담아.\n"
        "2) 항목 제목 대부분에 위 시험 구조의 실제 과목/파트/영역명을 넣어 공부 범위를 분명히 해 "
        "(예: '3과목 데이터베이스 구축 기출 풀이', 'RC Part5 문법 집중'). "
        "번호만 있는 기계적 분해('1단원 풀기')와 범위 없는 추상 표현('약점 보완'만)은 금지.\n"
        "3) title 은 20자 이하 한국어. 시험명(토익, JLPT 등) 접두사는 빼고 바로 과목/파트명으로 "
        "시작해 — 시험명은 이미 알고 있어. due_date 는 YYYY-MM-DD.\n"
        "4) summary_text 에 목표·기간 맞춤 전략을 1~2문장.\n"
        f"{shots}\n"
        "반드시 아래 JSON 형식으로만 출력:\n"
        '{"summary_text": "...", "todos": [{"title":"...","due_date":"YYYY-MM-DD"}], '
        '"calendar_events": [...]}'
    )


def _parse_llm_plan(
    content: str, *, today: date, horizon: int, exam_type: str
) -> PlanOutput:
    # 관용 로드+정규화: 트레일링 잡설/제어문자 허용, calendar_events 누락→[], due_date 별칭 매핑.
    data = _loads_lenient(content)
    plan = PlanOutput.model_validate(_normalize_plan_dict(data))
    errors = check_plan_consistency(plan, today=today, horizon_days=horizon)
    if errors:
        raise ValueError("inconsistent plan: " + "; ".join(errors))
    # 구체성 게이트: 과목/파트 키워드 없는 추상 플랜('약점 보완'만 나열) 거부 → 폴백.
    titles = [t.title for t in plan.todos] + [e.title for e in plan.calendar_events]
    ratio = concreteness_ratio(titles, exam_type)
    if ratio < CONCRETENESS_MIN:
        raise ValueError(f"abstract plan: concreteness {ratio:.2f} < {CONCRETENESS_MIN}")
    return plan


def synthesize_sample(
    seed: dict,
    *,
    today: date,
    client=None,
    model: str = "qwen2.5",
    temperature: float = 0.7,
    exemplars: list[dict] | None = None,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> dict:
    horizon = int(seed["days_left"])
    user = to_user_text(seed, today=today)
    by = "template"
    plan = _fallback_plan(seed, today)
    if client is not None:
        for attempt in range(1, LLM_ATTEMPTS + 1):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {
                            "role": "user",
                            "content": build_exam_prompt(
                                seed, today=today, exemplars=exemplars or []
                            ),
                        },
                    ],
                    temperature=temperature,
                    timeout=request_timeout,
                )
                plan = _parse_llm_plan(
                    resp.choices[0].message.content,
                    today=today,
                    horizon=horizon,
                    exam_type=seed["exam_type"],
                )
                by = "llm"
                break
            except Exception as exc:  # noqa: BLE001 - 어떤 실패든 안전하게 재시도→템플릿 폴백
                log.warning(
                    "exam 합성 LLM 시도 %d/%d 실패 (%s): %s",
                    attempt,
                    LLM_ATTEMPTS,
                    seed.get("exam_type"),
                    exc,
                )
        # 전 시도 실패 시 plan/by 는 함수 첫머리의 폴백 값 그대로다.

    return {
        "messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": dump_plan_for_training(plan)},
        ],
        "meta": {
            "provenance": "exam-synth",
            "task_type": "plan",
            "exam_type": seed["exam_type"],
            "time_left_days": horizon,
            "daily_hours": seed["daily_hours"],
            "level": seed["level"],
            "goal": seed["goal"],
            "note": seed["note"],
            "today": today.isoformat(),
            "synthesized_by": by,
        },
    }


def synthesize_to_file(
    seeds: list[dict],
    out_path: Path,
    *,
    today: date,
    client=None,
    model: str = "qwen2.5",
    exemplars: list[dict] | None = None,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    concurrency: int = 1,
) -> tuple[int, dict]:
    """시드를 합성해 한 줄씩 즉시 기록(flush). 중단돼도 진행분 보존.

    concurrency>1 이고 client 가 있으면 LLM 요청을 스레드로 동시 처리(기록은 메인 단일).
    순서는 보장하지 않는다(SFT는 셔플).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {"llm": 0, "template": 0}
    total = 0

    def _one(seed: dict) -> dict:
        return synthesize_sample(
            seed,
            today=today,
            client=client,
            model=model,
            exemplars=exemplars,
            request_timeout=request_timeout,
        )

    with open(out_path, "w", encoding="utf-8") as f:
        def _record(sample: dict) -> None:
            nonlocal total
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
            f.flush()
            counts[sample["meta"]["synthesized_by"]] += 1
            total += 1

        if client is None or concurrency <= 1:
            for seed in seeds:
                _record(_one(seed))
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                for fut in as_completed([pool.submit(_one, s) for s in seeds]):
                    _record(fut.result())
    return total, counts


def load_exemplars(path: Path, n: int = 2) -> list[dict]:
    """기존 exam.jsonl 에서 few-shot 그라운딩용 플랜 예시 n개를 읽는다."""
    out: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            out.append(json.loads(rec["messages"][-1]["content"]))
            if len(out) >= n:
                break
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="시험 플랜 합성 → exam_synth.jsonl")
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument("--total", type=int, default=1000, help="총 합성 수(시험종류별 균등)")
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--model", default="qwen2.5")
    parser.add_argument("--exemplars", type=Path, default=None, help="few-shot 그라운딩용 exam.jsonl")
    parser.add_argument("--exemplar-n", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT)
    parser.add_argument("--concurrency", type=int, default=1, help="LLM 동시요청 수(기본 1). 16~32 권장.")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="due_date 산술 기준일(YYYY-MM-DD). 미지정 시 오늘.",
    )
    args = parser.parse_args()

    today = args.today or date.today()
    seeds = build_seeds(args.total)
    client = make_local_client() if args.use_llm else None
    if args.use_llm and client is None:
        print("[exam_synth] warning: --use-llm 지정됐지만 모델 서버 설정이 없어 템플릿으로 대체합니다.")
    exemplars = (
        load_exemplars(args.exemplars, args.exemplar_n) if args.exemplars else []
    )
    total, counts = synthesize_to_file(
        seeds,
        args.out_path,
        today=today,
        client=client,
        model=args.model,
        exemplars=exemplars,
        request_timeout=args.timeout,
        concurrency=args.concurrency,
    )
    print(
        f"[exam_synth] {total} samples "
        f"({counts['llm']} llm / {counts['template']} template) -> {args.out_path}"
    )


if __name__ == "__main__":
    main()
