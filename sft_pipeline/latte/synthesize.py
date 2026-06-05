"""일상 시드(daily_seeds.csv) → 한국어 멀티턴 대화(daily_dialogs.jsonl).

provider-pluggable: OpenAI 호환 base_url 로 로컬 오픈모델(Ollama/vLLM)을 쓴다.
외부 배포 데이터라 ToS 안전을 위해 로컬 모델 사용을 권장한다.
모델이 없거나 출력이 깨지면 결정론적 템플릿으로 폴백해 오프라인에서도 동작한다.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_SYSTEM = (
    "너는 몽글마을의 다정하고 현실적인 일상 계획 도우미야. "
    "사용자의 할 일을 자연스러운 한국어 대화로 함께 계획해줘. "
    "주어진 장소와 시간대를 활용하되, 사실을 지어내지 말고 간결하게 제안해."
)


def build_synthesis_prompt(seed: dict) -> str:
    times = ", ".join(seed.get("times_ko", []))
    return (
        "다음 일상 할 일을 소재로, 한국어 멀티턴 대화를 만들어줘.\n"
        f"- 할 일(영문): {seed.get('task_title', '')}\n"
        f"- 장소: {seed.get('place_ko', '')}\n"
        f"- 추천 시간대: {times}\n\n"
        "요구사항:\n"
        "1) 영문 할 일을 자연스러운 한국어로 옮겨서 사용해.\n"
        "2) user가 계획을 요청 → assistant가 장소/시간대로 일정 제안 → "
        "user가 제약(시간 변경 등) 추가 → assistant가 조정, 이렇게 4턴 이상.\n"
        "3) 반드시 아래 JSON 형식으로만 출력:\n"
        '{"messages": [{"role": "user", "content": "..."}, '
        '{"role": "assistant", "content": "..."}]}'
    )


def _fallback_dialogue(seed: dict) -> list[dict]:
    task = seed.get("task_title", "할 일")
    place = seed.get("place_ko", "")
    times = seed.get("times_ko", [])
    times_str = ", ".join(times)
    first = times[0] if times else "여유 있는 시간"
    return [
        {"role": "user", "content": f"'{task}' 할 일을 계획하고 싶어. 언제 하는 게 좋을까?"},
        {
            "role": "assistant",
            "content": f"{place}에서 {times_str}에 하는 걸 추천해요. 그 시간대가 가장 여유로워 보여요.",
        },
        {"role": "user", "content": "혹시 다른 시간대도 괜찮을까?"},
        {
            "role": "assistant",
            "content": f"네, 사정이 생기면 옮겨도 돼요. 그래도 {place} 일정은 {first}이 가장 무난해요.",
        },
    ]


def _parse_llm_messages(content: str) -> list[dict]:
    data = json.loads(content)
    msgs = data["messages"] if isinstance(data, dict) else data
    if not isinstance(msgs, list) or len(msgs) < 2:
        raise ValueError("messages must be a list of >=2 turns")
    for m in msgs:
        if not isinstance(m, dict) or m.get("role") not in {"system", "user", "assistant"}:
            raise ValueError("invalid message role")
        if not str(m.get("content", "")).strip():
            raise ValueError("empty message content")
    if msgs[-1]["role"] != "assistant":
        raise ValueError("last turn must be assistant")
    return msgs


def synthesize_dialogue(seed: dict, *, client=None, model: str = "qwen2.5", temperature: float = 0.7) -> dict:
    by = "template"
    messages = _fallback_dialogue(seed)
    if client is not None:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": build_synthesis_prompt(seed)},
                ],
                temperature=temperature,
            )
            messages = _parse_llm_messages(resp.choices[0].message.content)
            by = "llm"
        except Exception as exc:  # noqa: BLE001 - 어떤 실패든 안전하게 템플릿 폴백
            log.warning("합성 LLM 실패, 템플릿 폴백 (seed id=%s): %s", seed.get("id"), exc)
            messages = _fallback_dialogue(seed)
            by = "template"

    return {
        "messages": messages,
        "meta": {
            "provenance": "daily-latte",
            "source_id": seed.get("id", ""),
            "license": "MIT",
            "place": seed.get("place_ko", ""),
            "times": seed.get("times_ko", []),
            "synthesized_by": by,
        },
    }


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


def write_jsonl(samples: list[dict], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="daily_seeds.csv → daily_dialogs.jsonl (멀티턴 합성)")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=None, help="합성할 시드 수(기본: 전체)")
    parser.add_argument("--use-llm", action="store_true", help="로컬 모델 합성(미지정 시 템플릿)")
    parser.add_argument("--model", default="qwen2.5")
    args = parser.parse_args()

    seeds = sample_seeds(dedup_seeds(load_seeds(args.in_path)), args.limit)
    client = make_local_client() if args.use_llm else None
    if args.use_llm and client is None:
        print("warning: --use-llm 지정됐지만 모델 서버 설정이 없어 템플릿으로 대체합니다.")
    samples = [synthesize_dialogue(s, client=client, model=args.model) for s in seeds]
    write_jsonl(samples, args.out_path)
    llm_n = sum(1 for s in samples if s["meta"]["synthesized_by"] == "llm")
    print(f"synthesized {len(samples)} dialogs ({llm_n} llm / {len(samples) - llm_n} template) -> {args.out_path}")


if __name__ == "__main__":
    main()
