"""导出人工复核用的两张表（UTF-8 BOM 的 CSV，Excel 可直接打开）。

1. review/label-review.csv：全部 200 条，带预标注，供逐条复核。
   在 `review_label` 列填写你认为正确的标签（同意就留空），`review_note` 写理由。
2. data/blind/blind-50.csv：固定随机种子抽 50 条、**不带标签**，用于自一致性检验。
   至少隔几天、并且不看 label-review.csv 的情况下，在 `label` 列盲标。

用法：python scripts/export_review_sheets.py
"""
from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from validate_dataset import ROOT, load_rows

SEED = 20261115
BLIND_SIZE = 50


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"已写入 {path.relative_to(ROOT)}（{len(rows)} 条）")


def main() -> None:
    rows = load_rows()
    posts = json.loads((ROOT / "data" / "posts.json").read_text(encoding="utf-8"))

    write_csv(
        ROOT / "review" / "label-review.csv",
        ["id", "seller_id", "post", "comment", "label", "hard_type", "uncertain", "note", "review_label", "review_note"],
        [[r["id"], r["seller_id"], posts[r["post_id"]]["text"], r["comment"], r["label"],
          r["hard_type"] or "", "Y" if r["uncertain"] else "", r["note"], "", ""] for r in rows],
    )

    blind_path = ROOT / "data" / "blind" / "blind-50.csv"
    if blind_path.exists():
        print(f"{blind_path.relative_to(ROOT)} 已存在，不覆盖（避免盲标结果被冲掉）")
        return
    sample = random.Random(SEED).sample([r for r in rows if not r["uncertain"]], BLIND_SIZE)
    write_csv(
        blind_path,
        ["id", "post", "comment", "label"],
        [[r["id"], posts[r["post_id"]]["text"], r["comment"], ""] for r in sorted(sample, key=lambda r: r["id"])],
    )


if __name__ == "__main__":
    main()
