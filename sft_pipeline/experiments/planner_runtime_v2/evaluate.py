"""현재 days 스키마용 LoRA 어댑터 회귀 평가."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from adapters.todo_creation._prompts import PLAN_GENERATOR_SYSTEM, plan_generator_user
from sft_pipeline.build.lib.plan_schemas import (
    check_runtime_plan_consistency,
    parse_runtime_plan,
)

BASE_MODEL = "Qwen/Qwen2.5-7B-Instruct"
EXAM_LEAK = ("필기", "실기", "기출", "약점 과목", "자격증")
ENGLISH_WORD = re.compile(r"[A-Za-z]{4,}")
ALLOWED_ACRONYMS = ("SQLD", "ADSP", "JLPT", "HSK", "CBT")


@dataclass(frozen=True)
class EvalCase:
    name: str
    kind: str
    goal: str
    deadline_days: int
    slots: dict[str, str]


CASES = (
    EvalCase("unknown_cooking", "project", "새 요리 경연 우승 준비", 24, {"success_criteria": "대표 요리 완성", "current_state": "가정 요리 경험", "available_time": "주 4회"}),
    EvalCase("unknown_audition", "project", "전국 노래 오디션 출연", 18, {"success_criteria": "지원 영상 완성", "current_state": "노래 경험 조금", "available_time": "평일 저녁"}),
    EvalCase("film_contest", "project", "단편영화 공모전 출품", 29, {"success_criteria": "완성본 제출", "current_state": "대본 초안 있음", "available_time": "주말 5시간"}),
    EvalCase("moving", "project", "새집 이사 준비", 12, {"success_criteria": "이삿날 이동 완료", "current_state": "업체만 예약", "available_time": "매일 1시간"}),
    EvalCase("portfolio", "project", "디자인 포트폴리오 개편", 45, {"success_criteria": "지원용 최종본", "current_state": "작업물 6개", "available_time": "주 3회"}),
    EvalCase("triathlon", "event", "철인 삼종 경기 완주", 45, {"success_criteria": "안전하게 완주", "current_state": "달리기만 경험", "available_time": "주 5회"}),
    EvalCase("half_marathon", "event", "첫 하프마라톤 완주", 21, {"success_criteria": "제한 시간 내 완주", "current_state": "5킬로미터 가능", "available_time": "주 4회"}),
    EvalCase("swim_event", "event", "바다 수영 대회 참가", 29, {"success_criteria": "정해진 거리 완영", "current_state": "수영장 경험", "available_time": "주 3회"}),
    EvalCase("tennis_event", "event", "동호인 테니스 대회 출전", 16, {"success_criteria": "두 경기 완주", "current_state": "초급", "available_time": "주 3회"}),
    EvalCase("trail_event", "event", "트레일 달리기 대회 완주", 60, {"success_criteria": "산길 코스 완주", "current_state": "평지 10킬로미터", "available_time": "주 4회"}),
    EvalCase("ipe_written", "exam", "정보처리기사 필기 합격", 20, {"exam_name": "정보처리기사", "exam_stage": "필기", "current_progress": "1과목 학습", "available_time": "하루 2시간"}),
    EvalCase("ipe_practical", "exam", "정보처리기사 실기 합격", 29, {"exam_name": "정보처리기사", "exam_stage": "실기", "current_progress": "용어 정리 중", "available_time": "하루 2시간"}),
    EvalCase("toeic", "exam", "토익 800점 달성", 14, {"exam_name": "토익", "target_score": "800점", "current_progress": "650점", "available_time": "평일 90분"}),
    EvalCase("opic", "exam", "오픽 IM2 달성", 10, {"exam_name": "오픽", "target_score": "IM2", "current_progress": "초급", "available_time": "매일 40분"}),
    EvalCase("sqld", "exam", "SQLD 자격증 합격", 25, {"exam_name": "SQLD", "current_progress": "개념 30퍼센트", "available_time": "하루 1시간"}),
    EvalCase("stretch", "routine", "아침 스트레칭 습관", 14, {"success_criteria": "주 5회 실천", "current_state": "불규칙", "available_time": "아침 15분"}),
    EvalCase("reading", "routine", "매일 독서하기", 21, {"success_criteria": "하루 20쪽", "current_state": "주말만 독서", "available_time": "취침 전 30분"}),
    EvalCase("sleep", "routine", "취침 시간 앞당기기", 12, {"success_criteria": "밤 11시 취침", "current_state": "새벽 1시 취침", "available_time": "매일"}),
    EvalCase("workout_study", "lifestyle", "운동과 영어 공부 병행", 29, {"success_criteria": "두 활동을 한 달 유지", "current_state": "둘 다 불규칙", "available_time": "평일 2시간"}),
    EvalCase("work_job", "lifestyle", "회사 일과 이직 준비 균형", 45, {"success_criteria": "지원서 3곳 제출", "current_state": "포트폴리오 초안", "available_time": "평일 저녁과 주말"}),
)


def _goal(case: EvalCase, today: date) -> dict:
    return {
        "intent": "plan",
        "plan_kind": case.kind,
        "slots": {"goal": case.goal, **case.slots},
        "goal_text": case.goal,
        "goal_tag": case.goal.replace(" ", "")[:20],
        "deadline": (today + timedelta(days=case.deadline_days)).isoformat(),
        "daily_capacity_minutes": 90,
        "personalization_patch": {"preferences": [], "constraints": []},
        "assumptions": [],
    }


def _load(adapter: str, base_model: str):
    import torch
    from peft import PeftConfig, PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    cfg = PeftConfig.from_pretrained(adapter)
    resolved_base = cfg.base_model_name_or_path or base_model
    tokenizer = AutoTokenizer.from_pretrained(adapter, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        resolved_base,
        torch_dtype=torch.float16,
        device_map="auto",
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model, tokenizer


def _generate(model, tokenizer, messages: list[dict], max_new_tokens: int) -> str:
    import torch

    inputs = tokenizer.apply_chat_template(
        messages, tokenize=True, add_generation_prompt=True, return_tensors="pt"
    ).to(model.device)
    with torch.no_grad():
        output = model.generate(
            input_ids=inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    return tokenizer.decode(output[0][inputs.shape[1] :], skip_special_tokens=True)


def _has_english_leak(text: str) -> bool:
    normalized = text.upper()
    for acronym in ALLOWED_ACRONYMS:
        normalized = normalized.replace(acronym, "")
    return bool(ENGLISH_WORD.search(normalized))


def evaluate(adapter: str, base_model: str, max_new_tokens: int) -> dict:
    model, tokenizer = _load(adapter, base_model)
    today = date(2026, 12, 1)
    results = []
    for case in CASES:
        goal = _goal(case, today)
        messages = [
            {"role": "system", "content": PLAN_GENERATOR_SYSTEM},
            {"role": "user", "content": plan_generator_user(parsed_goal=goal, today=today)},
        ]
        reply = _generate(model, tokenizer, messages, max_new_tokens)
        row = {
            "name": case.name,
            "kind": case.kind,
            "reply": reply,
            "parse_ok": False,
            "consistency_ok": False,
            "deadline_ok": False,
            "contamination_ok": False,
            "language_ok": False,
            "errors": [],
        }
        try:
            plan = parse_runtime_plan(reply)
            row["parse_ok"] = True
            consistency = check_runtime_plan_consistency(plan, today=today)
            row["consistency_ok"] = not consistency
            row["errors"].extend(consistency)
            last_date = max(day.date for day in plan.days)
            expected = today + timedelta(days=case.deadline_days)
            row["deadline_ok"] = (
                last_date == expected if case.deadline_days <= 29 else last_date <= today + timedelta(days=29)
            )
            combined = " ".join(
                [plan.summary_text]
                + [task.title for day in plan.days for task in day.tasks]
            )
            row["contamination_ok"] = case.kind == "exam" or not any(
                token in combined for token in EXAM_LEAK
            )
            row["language_ok"] = not _has_english_leak(combined)
        except Exception as exc:  # noqa: BLE001
            row["errors"].append(str(exc))
        results.append(row)

    def rate(key: str) -> float:
        return sum(bool(row[key]) for row in results) / len(results)

    return {
        "adapter": adapter,
        "n": len(results),
        "metrics": {
            "parse_rate": rate("parse_ok"),
            "consistency_rate": rate("consistency_ok"),
            "deadline_rate": rate("deadline_ok"),
            "contamination_pass_rate": rate("contamination_ok"),
            "korean_language_rate": rate("language_ok"),
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="planner runtime LoRA 평가")
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--base-model", default=BASE_MODEL)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=1200)
    parser.add_argument("--min-parse", type=float, default=0.85)
    parser.add_argument("--min-consistency", type=float, default=0.80)
    parser.add_argument("--min-deadline", type=float, default=0.75)
    args = parser.parse_args()
    report = evaluate(args.adapter, args.base_model, args.max_new_tokens)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    metrics = report["metrics"]
    passed = (
        metrics["parse_rate"] >= args.min_parse
        and metrics["consistency_rate"] >= args.min_consistency
        and metrics["deadline_rate"] >= args.min_deadline
        and metrics["contamination_pass_rate"] == 1.0
        and metrics["korean_language_rate"] == 1.0
    )
    if not passed:
        raise SystemExit("[eval] 승격 기준 미달")
    print("[eval] planner runtime v2 승격 기준 통과")


if __name__ == "__main__":
    main()
