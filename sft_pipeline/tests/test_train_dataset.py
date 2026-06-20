import json

from sft_pipeline.train.dataset import is_trainable, load_messages
from sft_pipeline.train.train_lora import DEFAULT_MODEL, parse_args


def test_parse_args_defaults():
    args = parse_args(["--train", "t.jsonl", "--out", "out"])
    assert str(args.train) == "t.jsonl"
    assert args.model == DEFAULT_MODEL  # 제품 모델 Qwen2.5-7B
    assert args.epochs == 2.0
    assert args.lr == 2e-4
    assert args.load_in_4bit is True


def test_parse_args_no_4bit_flag():
    args = parse_args(["--train", "t.jsonl", "--out", "o", "--no-4bit"])
    assert args.load_in_4bit is False


def _ok(asst: str = "계획이에요") -> dict:
    return {
        "messages": [
            {"role": "user", "content": "계획 짜줘"},
            {"role": "assistant", "content": asst},
        ],
        "meta": {"provenance": "daily-latte"},
    }


def test_is_trainable_true_for_nonempty_assistant():
    assert is_trainable(_ok()) is True


def test_is_trainable_false_for_empty_assistant():
    s = _ok(asst="   ")
    assert is_trainable(s) is False


def test_is_trainable_false_when_last_role_not_assistant():
    s = {"messages": [{"role": "user", "content": "hi"}]}
    assert is_trainable(s) is False


def test_is_trainable_false_for_missing_messages():
    assert is_trainable({"meta": {}}) is False


def test_load_messages_filters_untrainable(tmp_path):
    path = tmp_path / "train.jsonl"
    rows = [_ok("좋은 계획"), _ok("   "), _ok("또 다른 계획")]
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    out = load_messages(path)
    assert len(out) == 2  # 빈 assistant 1건 제거
    assert all(is_trainable(s) for s in out)


def test_load_messages_skips_blank_lines(tmp_path):
    path = tmp_path / "train.jsonl"
    path.write_text(
        json.dumps(_ok(), ensure_ascii=False) + "\n\n", encoding="utf-8"
    )
    assert len(load_messages(path)) == 1
