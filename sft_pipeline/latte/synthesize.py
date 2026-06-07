"""일상 시드(daily_seeds.csv) → 단일턴 구조화 플랜 샘플(daily.jsonl).

assistant 출력은 런타임 GenerateResult 미러(plan_schemas.PlanOutput) JSON 이다.
멀티턴 잡담 대신 '요청 → 구조화 플랜' 단일턴을 합성한다 — SFT 의 목표는
대화력이 아니라 출력의 구조·정합성이기 때문.

provider-pluggable: OpenAI 호환 base_url 로 로컬 오픈모델(Ollama/vLLM)을 쓴다.
외부 배포 데이터라 ToS 안전을 위해 로컬 모델 사용을 권장한다.
모델이 없거나 출력이 깨지거나 정합성 검증에 실패하면 결정론적 템플릿으로
폴백해 오프라인에서도 동작한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from sft_pipeline.build.plan_schemas import (
    PlanOutput,
    PlanTask,
    _loads_lenient,
    _normalize_plan_dict,
    check_plan_consistency,
)

log = logging.getLogger(__name__)

HORIZON_DAYS = 7  # 일상 할 일은 기준일로부터 7일 이내로 잡는다

_SYSTEM = (
    "너는 몽글마을의 다정하고 현실적인 일상 계획 도우미야. "
    "사용자의 할 일을 구조화된 JSON 플랜으로 정리해줘. "
    "사실을 지어내지 말고 주어진 장소와 시간대를 활용해."
)


def build_synthesis_prompt(seed: dict, *, today: date) -> str:
    times = ", ".join(seed.get("times_ko", []))
    return (
        "다음 일상 할 일로, 한국어 SFT 샘플(사용자 요청 + 구조화 플랜)을 만들어줘.\n"
        f"- 할 일(영문): {seed.get('task_title', '')}\n"
        f"- 장소: {seed.get('place_ko', '')}\n"
        f"- 추천 시간대: {times}\n"
        f"- 기준일(오늘): {today.isoformat()}\n\n"
        "요구사항:\n"
        "1) user 는 할 일을 자연스러운 한국어로 부탁하는 1~2문장.\n"
        f"2) plan.todos 에는 오늘({today.isoformat()}) 할 일만, "
        f"plan.calendar_events 에는 내일부터 {HORIZON_DAYS}일 이내 일만 담아.\n"
        "3) title 은 20자 이하 한국어, due_date 는 YYYY-MM-DD 형식.\n"
        "4) summary_text 에 장소·시간대 추천 이유를 1~2문장으로 적어.\n"
        "5) 반드시 아래 JSON 형식으로만 출력:\n"
        '{"user": "...", "plan": {"summary_text": "...", '
        '"todos": [{"title": "...", "due_date": "YYYY-MM-DD", "tags": []}], '
        '"calendar_events": [...]}}'
    )


def _fallback_parts(seed: dict, today: date) -> tuple[str, PlanOutput]:
    task = (seed.get("task_title") or "").strip() or "할 일"
    place = seed.get("place_ko", "")
    times = seed.get("times_ko", [])
    times_str = ", ".join(times) if times else "여유 있는 시간"
    tags = [t for t in [seed.get("broad_ko", "")] if t] or ["일상"]
    plan = PlanOutput(
        summary_text=f"{place}에서 {times_str}에 '{task}'을(를) 하는 걸 추천해요.",
        todos=[PlanTask(title=task[:20], due_date=today, tags=tags)],
        calendar_events=[],
    )
    user = f"'{task}' 할 일을 계획하고 싶어. 언제 하는 게 좋을까?"
    return user, plan


def _parse_llm_sample(content: str, *, today: date) -> tuple[str, PlanOutput]:
    # 관용 로드: 펜스/트레일링 잡설/제어문자 허용, 'Extra data'면 첫 객체만.
    data = _loads_lenient(content)
    if not isinstance(data, dict):
        raise ValueError("output must be a JSON object")
    user = str(data.get("user", "")).strip()
    if not user:
        raise ValueError("empty user request")
    # 관용 정규화: calendar_events/todos 누락→[], due_date 별칭 매핑, tags 기본값.
    plan = PlanOutput.model_validate(_normalize_plan_dict(data.get("plan")))
    errors = check_plan_consistency(plan, today=today, horizon_days=HORIZON_DAYS)
    if errors:
        raise ValueError("inconsistent plan: " + "; ".join(errors))
    return user, plan


DEFAULT_REQUEST_TIMEOUT = 60.0  # 단일 LLM 요청 상한(초). hang 시 무한대기 방지.


def synthesize_sample(
    seed: dict,
    *,
    today: date,
    client=None,
    model: str = "qwen2.5",
    temperature: float = 0.7,
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> dict:
    by = "template"
    user, plan = _fallback_parts(seed, today)
    if client is not None:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": build_synthesis_prompt(seed, today=today)},
                ],
                temperature=temperature,
                timeout=request_timeout,
            )
            user, plan = _parse_llm_sample(resp.choices[0].message.content, today=today)
            by = "llm"
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 안전하게 템플릿 폴백
            log.warning("합성 LLM 실패, 템플릿 폴백 (seed id=%s): %s", seed.get("id"), exc)
            user, plan = _fallback_parts(seed, today)
            by = "template"

    # due_date 산술의 앵커(기준일)는 항상 user 턴에 노출한다.
    anchor = today.isoformat()
    user_content = user if anchor in user else f"{user} (기준일: {anchor})"
    return {
        "messages": [
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": plan.model_dump_json()},
        ],
        "meta": {
            "provenance": "daily-latte",
            "turn_type": "single",
            "source_id": seed.get("id", ""),
            "license": "MIT",
            "place": seed.get("place_ko", ""),
            "times": seed.get("times_ko", []),
            "today": anchor,
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
    request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    concurrency: int = 1,
) -> tuple[int, dict]:
    """시드를 합성해 한 줄씩 즉시 기록(flush)한다.

    리스트에 전부 모았다가 끝에 한 번에 쓰지 않는다. 그래서 중단(KeyboardInterrupt,
    프로세스 종료 등)되어도 그 시점까지의 진행분은 파일에 남는다 — 장시간 본생성에서
    중단 시 전량 유실을 막는다. (총 기록 수, {"llm": n, "template": n})를 반환한다.

    concurrency>1 이고 client 가 있으면 LLM 요청을 스레드로 동시에 보낸다(I/O 바운드).
    기록은 항상 메인 스레드 한 곳에서만 하므로 파일 안전. 순서는 보장하지 않는다(SFT는 셔플).
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


def make_local_client(base_url: str | None = None, api_key: str | None = None):
    """OpenAI 호환 클라이언트. base_url 로 로컬 모델 서버(Ollama/vLLM)를 가리킨다.

    base_url 미지정 시 환경변수 LLM_BASE_URL → OPENAI_BASE_URL 순으로 본다.
    base_url 도 키도 없으면 None(→ 호출측은 템플릿 폴백).
    """
    import os

    base_url = base_url or os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    api_key = api_key or os.environ.get("OPENAI_API_KEY") or "not-needed"
    if not base_url and not os.environ.get("OPENAI_API_KEY"):
        return None
    from openai import OpenAI

    return OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)


def dedup_seeds(seeds: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for s in seeds:
        key = str(s.get("task_title", "")).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def sample_seeds(seeds: list[dict], limit: int | None) -> list[dict]:
    return seeds[:limit] if limit else seeds


def load_seeds(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["times_ko"] = [t for t in str(row.get("times_ko", "")).split(";") if t]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="daily_seeds.csv → daily.jsonl (단일턴 구조화 플랜 합성)")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None, help="합성할 시드 수(기본: 전체)")
    parser.add_argument("--use-llm", action="store_true", help="로컬 모델 합성(미지정 시 템플릿)")
    parser.add_argument("--model", default="qwen2.5")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="due_date 산술 기준일(YYYY-MM-DD). 미지정 시 오늘. 재현 빌드 시 고정 권장.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_REQUEST_TIMEOUT,
        help=f"단일 LLM 요청 타임아웃(초). 기본 {DEFAULT_REQUEST_TIMEOUT}.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="LLM 동시요청 수(I/O 바운드). 기본 1(순차). vLLM 배치 활용 시 16~32 권장.",
    )
    args = parser.parse_args()

    today = args.today or date.today()
    seeds = sample_seeds(dedup_seeds(load_seeds(args.in_path)), args.limit)
    client = make_local_client() if args.use_llm else None
    if args.use_llm and client is None:
        print("[synthesize] warning: --use-llm 지정됐지만 모델 서버 설정이 없어 템플릿으로 대체합니다.")
    total, counts = synthesize_to_file(
        seeds,
        args.out_path,
        today=today,
        client=client,
        model=args.model,
        request_timeout=args.timeout,
        concurrency=args.concurrency,
    )
    print(f"[synthesize] {total} samples ({counts['llm']} llm / {counts['template']} template) -> {args.out_path}")


if __name__ == "__main__":
    main()
