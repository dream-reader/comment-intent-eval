"""留出集：提示词 v2 的边界规则是看过难例集后补的，难例集上的成绩有过拟合嫌疑。
这里重新出一批没见过的难题，不按任何版本的失败挑选，全部保留，用来公平比较 v1 和 v2。

  python scripts/make_holdout.py generate   # deepseek-v4-pro 每个卖家出 25 条，排除已有评论
  python scripts/make_holdout.py sheet      # 打印 id 与评论原文，供盲标（不显示出题方预期）

产物：data/holdout/candidates.jsonl（含出题方预期，标注前不看）
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.agent import POSTS, extract_json  # noqa: E402
from agent.catalog import load_seller  # noqa: E402
from agent.llm import ROOT, LLMClient, load_config  # noqa: E402
from mine_hard_cases import LABELS, SELLERS, read_jsonl, write_jsonl  # noqa: E402
from validate_dataset import load_rows  # noqa: E402

OUT = ROOT / "data" / "holdout" / "candidates.jsonl"
PER_SELLER, MIN_PER_LABEL = 25, 5


def existing_comments(seller_id: str) -> list[str]:
    rows = [r["comment"] for r in load_rows("base") + load_rows("hard") if r["seller_id"] == seller_id]
    cand = ROOT / "data" / "hard" / "candidates.jsonl"
    rows += [r["comment"] for r in read_jsonl(cand) if r["seller_id"] == seller_id]
    return list(dict.fromkeys(rows))


def generate() -> None:
    cfg = load_config()
    llm = LLMClient(cfg)
    template = (ROOT / "evals" / "prompts" / "hard_case_generator.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "labeling-guide.md").read_text(encoding="utf-8")

    def one(seller_id: str) -> list[dict]:
        posts = {k: v["text"] for k, v in POSTS.items() if v["seller_id"] == seller_id}
        existing = existing_comments(seller_id)
        prompt = template.format(
            labeling_guide=guide,
            seller_json=json.dumps(load_seller(seller_id), ensure_ascii=False, indent=1),
            posts="\n".join(f"- {k}: {v}" for k, v in posts.items()),
            existing="\n".join(f"- {c}" for c in existing),
            n=PER_SELLER, min_per_label=MIN_PER_LABEL,
        )
        out = llm.chat(model=cfg["judge"]["model"], messages=[{"role": "user", "content": prompt}],
                       max_tokens=32000, temperature=1.0, response_format={"type": "json_object"})
        seen = {c.strip().lower() for c in existing}
        kept = [{"seller_id": seller_id, **it} for it in extract_json(out.message["content"])["items"]
                if it.get("post_id") in posts and it.get("intended_label") in LABELS
                and it.get("comment", "").strip().lower() not in seen]
        print(f"{seller_id}: 可用 {len(kept)} 条，用量 {out.usage.get('completion_tokens')} 输出 token")
        return kept

    with ThreadPoolExecutor(len(SELLERS)) as pool:
        rows = [r for batch in pool.map(one, SELLERS) for r in batch]
    for i, r in enumerate(rows, 1):
        r["id"] = f"o{i:03d}"
    write_jsonl(OUT, rows)
    print("共", len(rows), "条；预期标签分布:", Counter(r["intended_label"] for r in rows))


def sheet() -> None:
    for r in read_jsonl(OUT):
        print(r["id"], r["post_id"], "|", r["comment"].replace("\n", " "))


if __name__ == "__main__":
    {"generate": generate, "sheet": sheet}[sys.argv[1]]()
