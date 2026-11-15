"""校验评测集并输出分布统计。

用法：python scripts/validate_dataset.py [base|hard]
  base：基础评测集 data/eval/（默认）
  hard：对抗难例集 data/eval_hard/
校验规则来自 docs/labeling-guide.md 第 6 节；任何一条不合格都以非 0 退出。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPLITS = {"base": ROOT / "data" / "eval", "hard": ROOT / "data" / "eval_hard"}

LABELS = {"high", "medium", "low", "spam"}
PLATFORMS = {"linkedin", "facebook", "instagram", "tiktok"}
HARD_TYPES = {
    # 基础集
    "disguised_peer", "hidden_question", "minimal", "mixed_lang",
    "not_in_catalog", "injection", "boundary",
    # 难例集（见 evals/prompts/hard_case_generator.md）
    "implicit_high", "buried_signal", "buyer_looks_spam", "spam_looks_buyer",
    "negation", "third_party", "medium_low_edge", "code_switching", "subtle_injection",
}
REQUIRED = {"id", "seller_id", "platform", "post_id", "comment", "language", "label"}
OPTIONAL = {"uncertain", "hard_type", "note", "injection"}


def load_rows(split: str = "base") -> list[dict]:
    """读取某个数据集的 *.jsonl，补齐可选字段的默认值。"""
    rows = []
    for path in sorted(SPLITS[split].glob("*.jsonl")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            row.setdefault("uncertain", False)
            row.setdefault("hard_type", None)
            row.setdefault("note", "")
            row.setdefault("injection", False)
            row["_where"] = f"{path.name}:{lineno}"
            rows.append(row)
    return rows


def validate(rows: list[dict]) -> list[str]:
    sellers = {p.stem for p in (ROOT / "data" / "sellers").glob("*.json")}
    posts = json.loads((ROOT / "data" / "posts.json").read_text(encoding="utf-8"))
    errors, seen = [], set()
    for r in rows:
        where = r["_where"]
        keys = set(r) - {"_where"}
        if missing := REQUIRED - keys:
            errors.append(f"{where} 缺字段 {sorted(missing)}")
            continue
        if extra := keys - REQUIRED - OPTIONAL:
            errors.append(f"{where} 多余字段 {sorted(extra)}")
        if r["id"] in seen:
            errors.append(f"{where} id 重复 {r['id']}")
        seen.add(r["id"])
        if r["label"] not in LABELS:
            errors.append(f"{where} label 非法 {r['label']}")
        if r["platform"] not in PLATFORMS:
            errors.append(f"{where} platform 非法 {r['platform']}")
        if r["hard_type"] is not None and r["hard_type"] not in HARD_TYPES:
            errors.append(f"{where} hard_type 非法 {r['hard_type']}")
        if r["seller_id"] not in sellers:
            errors.append(f"{where} seller_id 不存在 {r['seller_id']}")
        post = posts.get(r["post_id"])
        if post is None:
            errors.append(f"{where} post_id 不存在 {r['post_id']}")
        elif post["seller_id"] != r["seller_id"]:
            errors.append(f"{where} post_id 与 seller_id 不匹配")
        if not r["comment"].strip():
            errors.append(f"{where} comment 为空")
        if not isinstance(r["injection"], bool):
            errors.append(f"{where} injection 必须是 true/false")
        elif r["injection"] and r["label"] != "spam":
            errors.append(f"{where} 含注入的样本标签必须是 spam")
        if r["uncertain"] and not r["note"]:
            errors.append(f"{where} uncertain 样本必须写 note")
    return errors


def pct(n: int, total: int) -> str:
    return f"{n:>4} ({n / total:5.1%})"


def report(rows: list[dict]) -> None:
    total = len(rows)
    print(f"共 {total} 条，uncertain {sum(r['uncertain'] for r in rows)} 条，含注入 {sum(r['injection'] for r in rows)} 条\n")
    for title, key in [("标签", "label"), ("卖家", "seller_id"), ("平台", "platform"), ("语言", "language")]:
        print(f"[{title}]")
        for k, n in Counter(r[key] for r in rows).most_common():
            print(f"  {k:<12}{pct(n, total)}")
    hard = [r for r in rows if r["hard_type"]]
    print(f"[难例] {pct(len(hard), total)}")
    for k, n in Counter(r["hard_type"] for r in hard).most_common():
        print(f"  {k:<16}{n}")


def main() -> int:
    split = sys.argv[1] if len(sys.argv) > 1 else "base"
    rows = load_rows(split)
    if not rows:
        print(f"{SPLITS[split]} 下没有数据")
        return 1
    errors = validate(rows)
    for e in errors:
        print("错误:", e)
    report(rows)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
