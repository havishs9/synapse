import numpy as np
import pytest

from backend import metrics as M


def test_per_class_and_macro():
    labels = ["a", "b", "c"]
    y = ["a", "a", "b", "c"]
    P = np.array([[0.9, 0.05, 0.05], [0.2, 0.7, 0.1], [0.1, 0.8, 0.1], [0.1, 0.1, 0.8]])
    m = M.classification_metrics(y, P, labels, primary="macro_f1")
    assert m["per_class"]["a"] == {"precision": 1.0, "recall": 0.5, "f1": pytest.approx(2 / 3), "support": 2}
    assert m["per_class"]["b"]["precision"] == 0.5 and m["per_class"]["b"]["recall"] == 1.0
    assert m["accuracy"] == 0.75
    assert m["primary"] == m["macro_f1"]


def test_recall_at_fpr():
    # 100 negatives scored 0..0.99, 10 positives: 5 above every negative, 5 in the middle
    neg = np.arange(100) / 100
    pos = np.array([1.5, 1.4, 1.3, 1.2, 1.1, 0.5, 0.4, 0.3, 0.2, 0.1])
    y = np.r_[np.zeros(100, bool), np.ones(10, bool)]
    s = np.r_[neg, pos]
    rec, thr = M.recall_at_fpr(y, s, 0.01)          # 1 negative may be above the threshold
    assert thr == pytest.approx(0.98)
    assert rec == 0.5
    rec0, _ = M.recall_at_fpr(y, s, 0.0)
    assert rec0 == 0.5
    rec10, _ = M.recall_at_fpr(y, s, 0.6)           # 60 negatives allowed above: threshold 0.39
    assert rec10 == 0.7


def test_binary_threshold_and_pr_auc():
    labels = ["anomaly", "normal"]
    y = ["anomaly", "normal", "normal", "anomaly"]
    P = np.array([[0.6, 0.4], [0.3, 0.7], [0.55, 0.45], [0.2, 0.8]])
    m = M.classification_metrics(y, P, labels, primary="recall_at_fpr", positive="anomaly", fpr_target=0.5,
                                 threshold=0.5)
    assert m["per_class"]["anomaly"]["recall"] == 0.5
    assert 0 < m["pr_auc"] <= 1


def test_ece_perfect_and_bad():
    assert M.expected_calibration_error(np.array([1.0, 1.0]), np.array([1, 1])) == 0
    assert M.expected_calibration_error(np.array([0.95, 0.95]), np.array([0, 0])) == pytest.approx(0.95)
