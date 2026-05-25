import json
from datetime import date

from agents.todo_creation.debug import (
    log_start, log_step, log_end, log_turn_input, log_turn_output,
)
from agents.todo_creation.schemas import MultiTurnInput, TurnResult


def test_multi_turn_uses_session_id_filename(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.todo_creation.debug._log_dir", lambda: tmp_path)
    inp = MultiTurnInput(
        user_id="alice", session_id="s-1", message="3일 후 시험",
        today=date(2026, 5, 25),
    )

    log_start(inp, "multi_turn")
    log_end(None)

    names = {p.name for p in tmp_path.iterdir()}
    assert "s-1_todo_multi_turn.log" in names
    assert "s-1_todo_multi_turn.jsonl" in names


def test_multi_turn_appends_across_turns(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.todo_creation.debug._log_dir", lambda: tmp_path)
    inp1 = MultiTurnInput(
        user_id="alice", session_id="s-1", message="첫번째",
        today=date(2026, 5, 25),
    )
    inp2 = inp1.model_copy(update={"message": "두번째"})

    log_start(inp1, "multi_turn"); log_end(None)
    log_start(inp2, "multi_turn"); log_end(None)

    body = (tmp_path / "s-1_todo_multi_turn.log").read_text()
    assert body.count("[todo_creation] start") == 2


def test_jsonl_sidecar_contains_step_updates(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.todo_creation.debug._log_dir", lambda: tmp_path)
    inp = MultiTurnInput(
        user_id="alice", session_id="s-2", message="msg",
        today=date(2026, 5, 25),
    )

    log_start(inp, "multi_turn")
    log_step(1, "validate", {"phase": "gathering"})
    log_end(None)

    entries = [
        json.loads(line)
        for line in (tmp_path / "s-2_todo_multi_turn.jsonl").read_text().strip().splitlines()
    ]
    kinds = [e["event"] for e in entries]
    assert kinds == ["start", "step", "end"]
    step = next(e for e in entries if e["event"] == "step")
    assert step["node"] == "validate"
    assert step["update"] == {"phase": "gathering"}


def test_log_turn_input_and_output(tmp_path, monkeypatch):
    monkeypatch.setattr("agents.todo_creation.debug._log_dir", lambda: tmp_path)
    inp = MultiTurnInput(
        user_id="alice", session_id="s-3", message="msg",
        today=date(2026, 5, 25),
    )

    log_start(inp, "multi_turn")
    log_turn_input("사용자 입력")
    log_turn_output(TurnResult(kind="question", question="언제까지?"))
    log_end(None)

    text = (tmp_path / "s-3_todo_multi_turn.log").read_text()
    assert "USER" in text and "사용자 입력" in text
    assert "BOT" in text and "언제까지?" in text

    events = [
        json.loads(line)
        for line in (tmp_path / "s-3_todo_multi_turn.jsonl").read_text().strip().splitlines()
    ]
    kinds = [e["event"] for e in events]
    assert "turn_input" in kinds and "turn_output" in kinds
