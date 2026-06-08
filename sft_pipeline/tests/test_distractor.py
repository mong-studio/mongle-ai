import collections

from sft_pipeline.build.distractor import (
    load_distractors,
    stratified_sample,
    to_sample,
)

_REC = {
    "id": 1,
    "messages": [
        {"role": "user", "content": "고마워"},
        {"role": "assistant", "content": "도움이 됐다면 다행이야. 더 정리할 일 생기면 말해줘."},
    ],
    "label": "todo",
    "is_distractor": True,
    "distractor_type": "thanks_chitchat",
    "source": "curated",
    "tone": "...",
}


def test_to_sample_maps_to_messages_meta():
    s = to_sample(_REC)
    assert s["messages"] == _REC["messages"]
    m = s["meta"]
    assert m["provenance"] == "distractor"
    assert m["task_type"] == "chat"
    assert "turn_type" not in m
    assert m["source_id"] == "1"
    assert m["label"] == "todo"
    assert m["distractor_type"] == "thanks_chitchat"
    assert "is_distractor" not in m
    assert m["source"] == "curated"


def _records():
    recs = []
    for t, n in [("a", 10), ("b", 20), ("c", 70)]:
        for i in range(n):
            recs.append(
                {
                    "id": f"{t}-{i:03d}",
                    "distractor_type": t,
                    "messages": [
                        {"role": "user", "content": f"u{i}"},
                        {"role": "assistant", "content": f"긴 답변 텍스트 {i} 입니다."},
                    ],
                    "label": "todo",
                    "source": "synthetic_aligned",
                }
            )
    return recs


def test_stratified_sample_preserves_type_proportions_and_is_deterministic():
    recs = _records()
    out1 = stratified_sample(recs, fraction=0.3)
    out2 = stratified_sample(recs, fraction=0.3)
    assert out1 == out2  # 결정론적
    counts = collections.Counter(r["distractor_type"] for r in out1)
    assert counts["a"] == 3
    assert counts["b"] == 6
    assert counts["c"] == 21
    assert len(out1) == 30


def test_stratified_sample_keeps_at_least_one_per_type():
    recs = [
        {"id": "x", "distractor_type": "rare", "messages": [], "label": "todo"},
    ]
    out = stratified_sample(recs, fraction=0.3)
    assert len(out) == 1


def test_load_distractors_reads_jsonl(tmp_path):
    import json

    p = tmp_path / "d.jsonl"
    p.write_text(json.dumps(_REC, ensure_ascii=False) + "\n", encoding="utf-8")
    recs = load_distractors(p)
    assert len(recs) == 1
    assert recs[0]["distractor_type"] == "thanks_chitchat"
