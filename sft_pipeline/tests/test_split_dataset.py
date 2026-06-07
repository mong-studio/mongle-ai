import collections

from sft_pipeline.build.split_dataset import dedup, stratified_split


def _sample(prov: str, user: str, asst: str = "ok") -> dict:
    return {
        "messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": asst},
        ],
        "meta": {"provenance": prov},
    }


def _by_prov(samples):
    return collections.Counter(s["meta"]["provenance"] for s in samples)


def _make_dataset():
    # provenance 별 개수: daily 20, exam-synth 20, distractor 10, exam-crawl 10
    out = []
    for i in range(20):
        out.append(_sample("daily-latte", f"daily {i}"))
    for i in range(20):
        out.append(_sample("exam-synth", f"exam {i}"))
    for i in range(10):
        out.append(_sample("distractor", f"chit {i}"))
    for i in range(10):
        out.append(_sample("exam-crawl", f"crawl {i}"))
    return out


def test_dedup_removes_exact_message_duplicates():
    samples = [_sample("daily-latte", "같은 내용"), _sample("daily-latte", "같은 내용")]
    out = dedup(samples)
    assert len(out) == 1


def test_dedup_keeps_different_content():
    samples = [_sample("daily-latte", "A"), _sample("daily-latte", "B")]
    assert len(dedup(samples)) == 2


def test_stratified_preserves_provenance_in_both_splits():
    """train/valid 모두 모든 출처를 비율대로 포함해야 한다(골고루)."""
    train, valid = stratified_split(_make_dataset(), ratio=0.8, seed=42)
    tprov, vprov = _by_prov(train), _by_prov(valid)
    for prov in ("daily-latte", "exam-synth", "distractor", "exam-crawl"):
        assert tprov[prov] > 0, f"{prov} train 누락"
        assert vprov[prov] > 0, f"{prov} valid 누락"
    # daily/exam-synth(각 20)는 distractor/exam-crawl(각 10)보다 train 비중이 커야 함
    assert tprov["daily-latte"] > tprov["distractor"]


def test_split_ratio_respected_overall():
    train, valid = stratified_split(_make_dataset(), ratio=0.8, seed=1)
    total = len(train) + len(valid)
    assert total == 60  # 입력 60건 보존(중복 없음)
    assert abs(len(train) / total - 0.8) < 0.1


def test_deterministic_same_seed():
    a = stratified_split(_make_dataset(), ratio=0.8, seed=7)
    b = stratified_split(_make_dataset(), ratio=0.8, seed=7)
    assert [s["messages"] for s in a[0]] == [s["messages"] for s in b[0]]
    assert [s["messages"] for s in a[1]] == [s["messages"] for s in b[1]]


def test_no_overlap_between_train_and_valid():
    import hashlib
    import json

    def key(s):
        return hashlib.sha256(
            json.dumps(s["messages"], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

    train, valid = stratified_split(_make_dataset(), ratio=0.8, seed=3)
    assert set(map(key, train)).isdisjoint(set(map(key, valid)))


def test_structure_preserved_passthrough():
    train, _ = stratified_split([_sample("daily-latte", "x", "계획이에요")], ratio=0.8, seed=0)
    s = train[0]
    assert [m["role"] for m in s["messages"]] == ["user", "assistant"]
    assert s["meta"]["provenance"] == "daily-latte"


def test_does_not_mutate_input():
    data = _make_dataset()
    snapshot = [s["messages"][0]["content"] for s in data]
    stratified_split(data, ratio=0.8, seed=0)
    assert [s["messages"][0]["content"] for s in data] == snapshot
