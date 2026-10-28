from collections import Counter

from backend.agents.data_agent import dedupe, rebalance_train, stratified_split


def rows(n_a, n_b, prefix="x"):
    return [{"id": f"{prefix}a{i}", "text": f"alpha {i}", "label": "a"} for i in range(n_a)] + \
           [{"id": f"{prefix}b{i}", "text": f"beta {i}", "label": "b"} for i in range(n_b)]


def test_dedupe_keeps_majority_label():
    rs = [{"id": "1", "text": "Laptop!", "label": "IT"}, {"id": "2", "text": "laptop", "label": "IT"},
          {"id": "3", "text": "LAPTOP", "label": "Office"}]
    out, info = dedupe(rs)
    assert len(out) == 1 and out[0]["label"] == "IT"
    assert info["duplicate_texts_with_conflicting_labels"] == 1


def test_split_is_stratified_and_disjoint():
    s = stratified_split(rows(500, 100), {"train": 0.6, "val": 0.2, "test": 0.2}, seed=1)
    ids = [r["id"] for part in s.values() for r in part]
    assert len(ids) == len(set(ids)) == 600
    for part in s.values():
        c = Counter(r["label"] for r in part)
        assert abs(c["b"] / sum(c.values()) - 100 / 600) < 0.02


def test_rebalance_applies_to_train_only():
    s = stratified_split(rows(500, 40), {"train": 0.6, "val": 0.2, "test": 0.2}, seed=2)
    before = {k: Counter(r["label"] for r in v) for k, v in s.items()}
    train, info = rebalance_train(s["train"], min_per_class=100, seed=0)
    assert Counter(r["label"] for r in train)["b"] == 100
    assert info["oversampled"]["b"] == 100 - before["train"]["b"]
    # val/test untouched: same objects, same class ratios
    assert Counter(r["label"] for r in s["val"]) == before["val"]
    assert Counter(r["label"] for r in s["test"]) == before["test"]
