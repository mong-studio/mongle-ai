import json
from pathlib import Path

from sft_pipeline.build.lib.validate_dataset import validate_samples


def _write(tmp_path: Path, samples: list[dict]) -> Path:
    path = tmp_path / "ds.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    return path


def _plan_json(todos=None, events=None, summary="기출 위주 반복 전략이에요."):
    return json.dumps(
        {
            "summary_text": summary,
            "todos": todos if todos is not None else [
                {"title": "핵심 개념 훑기", "due_date": "2026-06-06", "tags": ["공부"]}
            ],
            "calendar_events": events if events is not None else [
                {"title": "기출 1회차 풀이", "due_date": "2026-06-08", "tags": ["공부"]},
                {"title": "오답 정리·반복", "due_date": "2026-06-12", "tags": ["공부"]},
            ],
        },
        ensure_ascii=False,
    )


def _good():
    """시험준비 단일턴(user→assistant 구조화 플랜) 샘플."""
    return {
        "messages": [
            {
                "role": "user",
                "content": "다음 조건에 맞는 단기 시험 준비 계획을 세워줘.\n\n"
                "시험: 토익 / 남은 기간: D-7 / 기준일(오늘): 2026-06-06",
            },
            {"role": "assistant", "content": _plan_json()},
        ],
        "meta": {
            "provenance": "exam-crawl",
            "source_url": "https://example.com/1",
            "exam_type": "토익",
            "result": "합격",
            "today": "2026-06-06",
            "time_left_days": 7,
        },
    }


def _good_daily():
    """일상 단일턴(MS-LaTTE 유래) 샘플 - exam 필드 없이 provenance만 다르다."""
    return {
        "messages": [
            {"role": "user", "content": "주말에 장보기 계획 좀 짜줘. (기준일: 2026-06-06)"},
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "summary_text": "주말 아침 마트가 한가해서 추천해요.",
                        "todos": [],
                        "calendar_events": [
                            {"title": "마트 장보기", "due_date": "2026-06-07", "tags": ["장보기"]}
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "meta": {
            "provenance": "daily-latte",
            "source_id": "latte-000123",
            "license": "MIT",
            "today": "2026-06-06",
        },
    }


def test_valid_exam_sample_passes(tmp_path):
    """구조화 플랜을 갖춘 정상 시험 샘플은 통과(ok=1)하고 오류가 없는지 확인."""
    report = validate_samples(_write(tmp_path, [_good()]))
    assert report["ok"] == 1
    assert report["errors"] == []


def test_valid_daily_sample_passes(tmp_path):
    """exam_type/result 없는 일상 단일턴 샘플도 통일 스키마에서 통과하는지 확인."""
    report = validate_samples(_write(tmp_path, [_good_daily()]))
    assert report["ok"] == 1
    assert report["errors"] == []


def test_missing_messages_flagged(tmp_path):
    """필수 키(messages)가 빠지면 오류로 보고하는지 확인."""
    bad = _good()
    del bad["messages"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("messages" in e for e in report["errors"])


def test_last_must_be_assistant(tmp_path):
    """대화의 마지막 턴이 assistant가 아니면 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"].append({"role": "user", "content": "고마워!"})  # user로 끝남
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("last" in e or "assistant" in e for e in report["errors"])


def test_empty_content_flagged(tmp_path):
    """빈 content 메시지는 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = "   "
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("empty" in e for e in report["errors"])


def test_raw_copy_flagged(tmp_path):
    """assistant가 직전 user 메시지를 그대로 복붙하면 raw_copy 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = bad["messages"][0]["content"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("raw_copy" in e for e in report["errors"])


def test_exam_provenance_missing_meta_flagged(tmp_path):
    """provenance=exam-crawl인데 exam_type이 없으면 오류로 잡는지 확인."""
    bad = _good()
    del bad["meta"]["exam_type"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("exam_type" in e for e in report["errors"])


# === 구조화 플랜 정합성 ===


def test_non_json_assistant_flagged(tmp_path):
    """assistant 출력이 구조화 플랜 JSON이 아니면 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = "[토익 · D-7 준비 플랜] 매일 모의고사 1회분 풀기."
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("plan" in e for e in report["errors"])


def test_missing_today_meta_flagged(tmp_path):
    """meta.today(기준일 앵커)가 없으면 정합성 검증 불가 → 오류."""
    bad = _good()
    del bad["meta"]["today"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("today" in e for e in report["errors"])


def test_date_beyond_horizon_flagged(tmp_path):
    """D-7인데 기준일+7일 밖 due_date가 있으면 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = _plan_json(
        events=[{"title": "기출 풀이", "due_date": "2026-07-01", "tags": []}]
    )
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("horizon" in e and "초과" in e for e in report["errors"])


def test_branching_violation_flagged(tmp_path):
    """미래 날짜 task가 todos에 있으면 C5 분기 위반 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = _plan_json(
        todos=[{"title": "기출 풀이", "due_date": "2026-06-08", "tags": []}]
    )
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("todos" in e and "오늘" in e for e in report["errors"])


def test_monotonic_decomposition_flagged(tmp_path):
    """'1단원, 2단원...' 식 기계적 분해가 과반이면 품질 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = _plan_json(
        todos=[],
        events=[
            {"title": f"{i}단원 풀기", "due_date": "2026-06-08", "tags": []}
            for i in range(1, 4)
        ],
    )
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("단조 분해" in e for e in report["errors"])


# === distractor(네거티브) - 평문 대화라 2층(플랜 정합성)을 건너뛴다 ===


def _good_distractor():
    """distractor 단일턴: assistant 가 플랜 JSON 이 아니라 평문 대화. today 없음."""
    return {
        "messages": [
            {"role": "user", "content": "고마워"},
            {
                "role": "assistant",
                "content": "도움이 됐다면 다행이야. 더 정리할 일 생기면 이어서 말해줘.",
            },
        ],
        "meta": {
            "provenance": "distractor",
            "distractor_type": "thanks_chitchat",
            "is_distractor": True,
            "source_id": "1",
        },
    }


def test_distractor_passes_layer1_only(tmp_path):
    """평문 assistant·meta.today 없음이어도 distractor 는 1층만 통과하면 OK."""
    report = validate_samples(_write(tmp_path, [_good_distractor()]))
    assert report["ok"] == 1
    assert report["errors"] == []


def test_distractor_still_gets_layer1_hygiene(tmp_path):
    """distractor 라도 1층(형식) 검사는 적용 - 빈 content 는 잡힌다."""
    bad = _good_distractor()
    bad["messages"][1]["content"] = "   "
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("empty" in e for e in report["errors"])


# === exam-synth(합성 시험) - 플랜 정합성 검사(horizon=time_left_days) ===


def _good_exam_synth():
    return {
        "messages": [
            {
                "role": "user",
                "content": "다음 조건에 맞는 단기 시험 준비 계획을 세워줘.\n\n"
                "시험: 토익 / 남은 기간: D-14 / 목표: 900점 / 기준일(오늘): 2026-06-06",
            },
            {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "summary_text": "기출 회독 후 약점 보완에 집중하는 전략이에요.",
                        "todos": [{"title": "핵심 개념 훑기", "due_date": "2026-06-06", "tags": ["공부"]}],
                        "calendar_events": [
                            {"title": "기출 풀이와 오답 점검", "due_date": "2026-06-10", "tags": ["공부"]}
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "meta": {
            "provenance": "exam-synth",
            "exam_type": "토익",
            "time_left_days": 14,
            "today": "2026-06-06",
        },
    }


def test_exam_synth_validates_as_plan(tmp_path):
    report = validate_samples(_write(tmp_path, [_good_exam_synth()]))
    assert report["ok"] == 1, report["errors"]


def test_exam_synth_missing_meta_flagged(tmp_path):
    bad = _good_exam_synth()
    del bad["meta"]["exam_type"]
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("exam_type" in e for e in report["errors"])


# === 언어 게이트(비한국어 스크립트 혼입) - 모든 출처의 1층 검사 ===


def test_kana_in_assistant_flagged(tmp_path):
    """가나(일본어)가 한 글자라도 있으면 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = _plan_json(summary="모의고사를 풀고 オ답을 정리해요.")
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("non-korean script" in e and "kana" in e for e in report["errors"])


def test_cyrillic_in_assistant_flagged(tmp_path):
    """키릴 문자가 섞이면 오류로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = _plan_json(summary="기출 위주 반복 стратегия 전략이에요.")
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("non-korean script" in e and "cyrillic" in e for e in report["errors"])


def test_han_heavy_content_flagged(tmp_path):
    """한자 비율이 임계(2%)를 넘으면 중국어 혼입으로 잡는지 확인."""
    bad = _good()
    bad["messages"][1]["content"] = _plan_json(summary="先做模拟考试然后整理错题并且反复复习重要的概念")
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("han ratio" in e for e in report["errors"])


def test_natural_hanja_annotation_passes(tmp_path):
    """한국어 문장 속 소량 한자 병기(讃美 등)는 통과하는지 확인."""
    ok = _good()
    ok["messages"][1]["content"] = _plan_json(
        summary="찬미(讃美)의 뜻을 짚고 기출 위주로 반복하는 전략이에요. "
        "오답 정리와 복습을 매일 이어가면 부담이 적어요."
    )
    report = validate_samples(_write(tmp_path, [ok]))
    assert report["ok"] == 1, report["errors"]


def test_user_turn_language_also_checked(tmp_path):
    """user 턴(합성 입력)에 섞인 비한국어도 잡는지 확인."""
    bad = _good_distractor()
    bad["messages"][0]["content"] = "ありがとう 고마워"
    report = validate_samples(_write(tmp_path, [bad]))
    assert any("non-korean script" in e and "kana" in e for e in report["errors"])


def test_daily_crawl_horizon_days():
    from sft_pipeline.build.lib.validate_dataset import PLAN_PROVENANCES, _horizon_days
    assert "daily-crawl" not in PLAN_PROVENANCES
    assert _horizon_days({"provenance": "daily-crawl"}) == 7


def test_daily_critic_not_in_plan_provenances():
    from sft_pipeline.build.lib.validate_dataset import PLAN_PROVENANCES
    assert "daily-critic" not in PLAN_PROVENANCES
