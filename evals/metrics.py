"""分类指标：混淆矩阵、每类精确率/召回率/F1、宏平均 F1、分组准确率。

uncertain 样本不进入主指标（标准答案本身不可靠）。
输出不可解析的样本记为预测 "invalid"，算判错。
"""
from __future__ import annotations

from collections import Counter, defaultdict

LABELS = ["high", "medium", "low", "spam"]


def predicted_label(record: dict) -> str:
    parsed = record.get("parsed")
    return parsed["label"] if parsed and not record.get("error") else "invalid"


def classification(pairs: list[tuple[str, str]]) -> dict:
    """pairs: [(gold, pred)]，返回准确率、每类指标、宏平均 F1、混淆矩阵。"""
    n = len(pairs)
    cm = Counter(pairs)
    per_class = {}
    for label in LABELS:
        tp = cm[(label, label)]
        fp = sum(c for (g, p), c in cm.items() if p == label and g != label)
        fn = sum(c for (g, p), c in cm.items() if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": tp + fn}
    return {
        "n": n,
        "accuracy": sum(cm[(l, l)] for l in LABELS) / n if n else 0.0,
        "macro_f1": sum(v["f1"] for v in per_class.values()) / len(LABELS),
        "per_class": per_class,
        "confusion": cm,
    }


def grouped_accuracy(rows: list[tuple[dict, str]], key) -> list[tuple[str, int, float]]:
    """rows: [(sample, pred)]；key(sample) 给出分组名。返回 [(组名, 条数, 准确率)]，按准确率升序。"""
    groups = defaultdict(list)
    for sample, pred in rows:
        groups[key(sample)].append(sample["label"] == pred)
    return sorted(((k, len(v), sum(v) / len(v)) for k, v in groups.items()), key=lambda x: (x[2], -x[1]))
