"""SFT JSONL 품질 검사. messages 형식 검사 + 구조화 플랜(JSON) 정합성.

1층(형식): messages 스키마·빈값·역할 순서·직전 user 복붙 휴리스틱.
2층(정합성): 마지막 assistant 출력을 PlanOutput 으로 파싱해
  날짜 범위(meta.today ~ +horizon)·todos/calendar_events 분기(C5)·분량·
  단조 분해('N단원/N일차' 과반) 위반을 잡는다.

참고: 원문(블로그) 표절 방지는 상류 단계의 책임이다 - actual_plan_summary 는
사람이 재서술한 요약이어야 하며(원문 복붙 금지), 이는 수집 검수 체크리스트
(reports/preprocessing_report_template.md)와 README 가이드로 강제한다.

meta.provenance 로 출처를 구분하며, exam-crawl 출처에만 exam_type/result 를 강제한다.
horizon 은 exam-crawl 이면 meta.time_left_days, daily-latte 면 7일이다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from sft_pipeline.build.plan_schemas import check_plan_consistency, parse_plan

# 모든 샘플(JSONL 한 줄 = 학습 데이터 한 개)이 반드시 가져야 하는 키
# "messages"(대화 내용)와 "meta"(부가 정보) 둘 다 있어야 함
REQUIRED_KEYS = {"messages", "meta"}

# 출처가 "시험 크롤링(exam-crawl)"인 샘플이라면 meta 안에 꼭 들어 있어야
# 하는 추가 정보들 (어느 글에서 가져왔는지, 무슨 시험인지, 결과는 어땠는지)
EXAM_REQUIRED_META = {"source_url", "exam_type", "result"}

# 대화에서 말하는 사람(role)으로 허용되는 이름 세 가지
# system(규칙 설명), user(질문하는 사람), assistant(답하는 AI)만 가능
VALID_ROLES = {"system", "user", "assistant"}

# 마지막 assistant(AI) 답변은 최소 이만큼(20글자)은 길어야 함
# 너무 짧으면 제대로 된 플랜이 아닐 가능성이 높기 때문
MIN_OUTPUT_LEN = 20

# 일상(daily-latte) 데이터의 플랜은 "오늘부터 7일 안"의 날짜만 허용
# latte.synthesize.HORIZON_DAYS 와 같은 값을 쓰는 게 정책
DAILY_HORIZON_DAYS = 7

# 마지막 assistant 출력이 "구조화 플랜 JSON"이어야 하는 출처들.
# 이 출처만 2층(플랜 정합성) 검사를 받는다. distractor 처럼 의도적으로 평문 대화인
# 출처는 2층을 건너뛰고 1층(형식 위생)만 검사한다.
PLAN_PROVENANCES = {"exam-crawl", "daily-latte", "exam-synth"}


def _validate_messages(messages, idx: int) -> list[str]:
    """대화(messages)가 올바른 모양인지 검사한다 (1층: 형식 검사)

    보낸 사람 이름(role)이 있는지, 내용(content)이 비어 있지 않은지,
    마지막 답장이 AI(assistant)의 것인지 등을 본다.
    문제가 있으면 "몇 번째 줄에 무엇이 잘못됐다"는 설명을 모아 돌려줌
    """
    errors: list[str] = []
    # [검사 1] messages 는 리스트여야 하고, 최소 2개의 대화(질문+답변)가 있어야 함
    # 질문만 있거나 답변만 있으면 학습 데이터로 쓸 수 없음
    if not isinstance(messages, list) or len(messages) < 2:
        return [f"line {idx}: messages must be a list of >=2 turns"]

    # [검사 2] 대화 하나하나를 돌면서 기본 모양을 확인
    for j, m in enumerate(messages):
        # 각 대화는 딕셔너리이고, role(누가)·content(무슨 말) 둘 다 있어야 함
        if not isinstance(m, dict) or "role" not in m or "content" not in m:
            errors.append(f"line {idx}: message {j} missing role/content")
            continue
        # role 은 system/user/assistant 셋 중 하나여야 함
        if m["role"] not in VALID_ROLES:
            errors.append(f"line {idx}: message {j} invalid role {m['role']!r}")
        # 내용이 비어 있거나 공백뿐이면 안 됨
        if not str(m["content"]).strip():
            errors.append(f"line {idx}: message {j} empty content")
    # 기본 모양부터 틀렸다면 아래의 순서 검사는 의미가 없으니 여기서 멈춤
    if errors:
        return errors

    # [검사 3] 대화의 "순서"를 확인
    roles = [m["role"] for m in messages]
    # 사용자의 질문(user)이 하나도 없으면 "질문 없는 답변"이라 잘못된 데이터
    if "user" not in roles:
        errors.append(f"line {idx}: no user turn")
    # 마지막 말은 반드시 AI(assistant)의 답변이어야 함
    # 학습할 때 "마지막 답변"을 정답으로 쓰기 때문
    if roles[-1] != "assistant":
        errors.append(f"line {idx}: last turn must be assistant")
        return errors

    # [검사 4] 마지막 AI 답변의 품질을 간단히 확인
    last = str(messages[-1]["content"]).strip()
    # 답변이 너무 짧으면(20글자 미만) 제대로 된 플랜이 아닐 가능성이 큼
    if len(last) < MIN_OUTPUT_LEN:
        errors.append(f"line {idx}: last assistant too short (<{MIN_OUTPUT_LEN})")
    # 마지막 답변 "바로 앞"에 나온 사용자 질문을 찾는다
    # (뒤에서부터 거꾸로 훑어 처음 만나는 user 메시지, 없으면 빈 문자열)
    prev_user = next(
        (
            str(m["content"]).strip()
            for m in reversed(messages[:-1])
            if m["role"] == "user"
        ),
        "",
    )
    # AI 답변이 사용자 질문을 글자 그대로 복사(복붙)한 것이면 학습에 해로우니 걸러냄
    if last and last == prev_user:
        errors.append(f"line {idx}: raw_copy (assistant == preceding user)")
    return errors


def _validate_meta(meta: dict, idx: int) -> list[str]:
    """부가 정보(meta)에 필요한 항목이 다 있는지 검사한다

    모든 샘플은 "이 데이터가 어디서 왔는지"(provenance)를 적어야 하고,
    시험 크롤링(exam-crawl) 출처라면 출처 주소·시험 종류·결과까지
    빠짐없이 적혀 있어야 한다
    """
    errors: list[str] = []
    # provenance(출처)는 모든 샘플의 필수 항목
    if "provenance" not in meta:
        errors.append(f"line {idx}: meta missing ['provenance']")
    # 시험 크롤링 출처라면 추가 필수 항목 3개가 모두 있는지 확인
    # (집합 빼기: "필요한 키" - "실제 있는 키" = "빠진 키")
    if meta.get("provenance") == "exam-crawl":
        missing = EXAM_REQUIRED_META - set(meta)
        if missing:
            errors.append(f"line {idx}: meta missing {sorted(missing)}")
    # 합성 시험(exam-synth)은 원문 출처가 없으니 source_url/result 는 요구하지 않고,
    # 플랜 정합성에 필요한 exam_type/time_left_days 만 강제한다.
    elif meta.get("provenance") == "exam-synth":
        missing = {"exam_type", "time_left_days"} - set(meta)
        if missing:
            errors.append(f"line {idx}: meta missing {sorted(missing)}")
    return errors


def _horizon_days(meta: dict) -> int | None:
    """플랜에 허용되는 날짜 범위(오늘부터 며칠까지)를 계산한다

    - 시험 크롤링(exam-crawl): 시험까지 남은 일수(time_left_days)가 그 기간
      (숫자가 아니거나 0 이하면 None → 날짜 범위 검사를 건너뜀)
    - 일상(daily-latte) 등 나머지: 항상 7일(DAILY_HORIZON_DAYS)
    """
    if meta.get("provenance") in {"exam-crawl", "exam-synth"}:
        days = meta.get("time_left_days")
        return int(days) if isinstance(days, (int, float)) and days > 0 else None
    return DAILY_HORIZON_DAYS


def _validate_plan(sample: dict, idx: int) -> list[str]:
    """마지막 AI 답변(플랜 JSON)의 내용이 말이 되는지 검사한다 (2층: 정합성 검사)

    순서: ① 기준 날짜(meta.today)를 읽고 → ② 답변을 플랜(JSON)으로 해석하고
    → ③ "날짜가 범위 밖이다", "할 일이 너무 적다" 같은 논리 문제를 찾는다
    """
    meta = sample.get("meta") or {}
    # ① 기준 날짜(today)가 있어야 "플랜의 날짜가 맞는지"를 잴 수 있다
    #    (자 없이 길이를 잴 수 없는 것처럼, today 없이는 날짜 검사를 못 함)
    today_raw = meta.get("today")
    if not today_raw:
        return [f"line {idx}: meta missing ['today'] (plan 정합성 앵커)"]
    # 날짜 글자("2026-06-06" 모양)를 진짜 날짜로 바꿔본다. 모양이 틀리면 에러
    try:
        today = date.fromisoformat(str(today_raw))
    except ValueError:
        return [f"line {idx}: meta.today invalid date {today_raw!r}"]
    # ② 마지막 AI 답변을 플랜(PlanOutput)으로 해석한다. JSON 이 아니거나
    #    스키마(정해진 모양)에 안 맞으면 여기서 에러
    try:
        plan = parse_plan(str(sample["messages"][-1]["content"]))
    except ValueError as exc:
        return [f"line {idx}: invalid plan output ({exc})"]
    # ③ 허용 날짜 범위를 구한 뒤, 플랜 내용의 논리 검사를 돌린다
    #    발견된 문제마다 "몇 번째 줄의 플랜 문제"라고 앞에 줄 번호를 붙여 돌려줌
    horizon = _horizon_days(meta)
    return [
        f"line {idx}: plan {e}"
        for e in check_plan_consistency(plan, today=today, horizon_days=horizon)
    ]


def _validate_one(sample: dict, idx: int) -> list[str]:
    """샘플 한 개를 처음부터 끝까지 검사한다 (검사 순서의 총감독)

    순서: 필수 키 확인 → 1층(대화 형식 + meta) → 통과하면 2층(플랜 정합성)
    """
    # 필수 키(messages, meta)가 빠졌으면 더 볼 것도 없이 바로 에러
    missing = REQUIRED_KEYS - set(sample)
    if missing:
        return [f"line {idx}: missing keys {sorted(missing)}"]
    # 1층 검사: 대화 모양 + 부가 정보
    errors = _validate_messages(sample.get("messages"), idx)
    errors += _validate_meta(sample.get("meta") or {}, idx)
    if not errors:
        # 형식 검사를 통과한 샘플만 2층(플랜 정합성)으로 내려보냄
        # (모양이 깨진 데이터에 플랜 검사를 하면 엉뚱한 에러만 나오기 때문)
        # 단, distractor 처럼 의도적으로 평문 대화인 출처는 플랜이 아니므로 2층을 건너뛴다.
        provenance = (sample.get("meta") or {}).get("provenance")
        if provenance in PLAN_PROVENANCES:
            errors += _validate_plan(sample, idx)
    return errors


def validate_samples(path: Path) -> dict:
    """JSONL 파일 전체를 한 줄씩 검사해서 성적표를 만든다

    돌려주는 값: {"ok": 통과한 줄 수, "errors": 발견된 문제 설명 목록}
    """
    errors: list[str] = []
    ok = 0
    with open(path, encoding="utf-8") as f:
        # 한 줄 = 샘플 한 개. 줄 번호(idx)는 1부터 세서 에러 메시지에 쓴다
        for idx, line in enumerate(f, start=1):
            # 빈 줄은 데이터가 아니므로 그냥 건너뜀
            if not line.strip():
                continue
            # 줄이 올바른 JSON 인지부터 확인. 깨진 JSON 이면 다음 줄로 넘어감
            try:
                sample = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {idx}: invalid json ({exc})")
                continue
            # 샘플 하나를 전체 검사하고, 문제가 없으면 통과(ok) 하나 추가
            line_errors = _validate_one(sample, idx)
            if line_errors:
                errors.extend(line_errors)
            else:
                ok += 1
    return {"ok": ok, "errors": errors}


def main() -> None:
    """터미널에서 직접 실행할 때의 입구

    사용법: python validate_dataset.py --in 데이터파일.jsonl
    결과를 출력하고, 에러가 하나라도 있으면 실패 코드(1)로 끝난다
    (그래야 자동화 스크립트가 "검사 실패"를 알아챌 수 있음)
    """
    parser = argparse.ArgumentParser(description="SFT JSONL 품질 검사")
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    args = parser.parse_args()
    report = validate_samples(args.in_path)
    # 요약 한 줄(통과/에러 개수) + 에러 상세 목록을 출력
    print(f"[validate] ok={report['ok']} errors={len(report['errors'])}")
    for err in report["errors"]:
        print(f"[validate]   - {err}")
    sys.exit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
