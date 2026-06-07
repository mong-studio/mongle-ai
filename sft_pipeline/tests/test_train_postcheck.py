import json

from sft_pipeline.train.postcheck import (
    ends_with_eos,
    overfit_warning,
    parse_success_rate,
    read_eval_loss,
)

_VALID = json.dumps(
    {
        "summary_text": "좋은 계획이에요",
        "todos": [{"title": "오늘 공부", "due_date": "2026-06-06", "tags": ["공부"]}],
        "calendar_events": [],
    },
    ensure_ascii=False,
)
_INVALID_JSON = "이건 JSON이 아니에요"
_MISSING_FIELD = json.dumps({"summary_text": "todos 없음"}, ensure_ascii=False)


def test_parse_success_rate_all_valid():
    r = parse_success_rate([_VALID, _VALID])
    assert r["rate"] == 1.0
    assert r["n"] == 2
    assert r["failures"] == []


def test_parse_success_rate_counts_failures():
    r = parse_success_rate([_VALID, _INVALID_JSON, _MISSING_FIELD])
    assert r["n"] == 3
    assert abs(r["rate"] - 1 / 3) < 1e-9
    assert len(r["failures"]) == 2  # 깨진 JSON + 필수필드 누락


def test_parse_success_rate_empty():
    r = parse_success_rate([])
    assert r["rate"] == 0.0
    assert r["n"] == 0


def test_ends_with_eos_true():
    assert ends_with_eos("계획이에요<|im_end|>") is True
    assert ends_with_eos("계획이에요<|im_end|>\n") is True  # 뒤 공백 허용


def test_ends_with_eos_false():
    assert ends_with_eos("계획이 끊겨서 안 끝났") is False


def test_overfit_warning_triggers_below_threshold():
    msg = overfit_warning(0.12, threshold=0.2)
    assert msg is not None
    assert "과적합" in msg


def test_overfit_warning_none_above_threshold():
    assert overfit_warning(0.45, threshold=0.2) is None


def test_overfit_warning_none_when_loss_missing():
    assert overfit_warning(None) is None


def test_read_eval_loss_from_trainer_state(tmp_path):
    ckpt = tmp_path / "checkpoints"
    ckpt.mkdir()
    state = {
        "log_history": [
            {"loss": 1.2, "step": 10},
            {"eval_loss": 0.6, "step": 20},
            {"loss": 0.3, "step": 30},
            {"eval_loss": 0.18, "step": 40},
        ]
    }
    (ckpt / "trainer_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    assert read_eval_loss(ckpt) == 0.18  # 마지막 eval_loss


def test_read_eval_loss_missing_returns_none(tmp_path):
    assert read_eval_loss(tmp_path) is None
