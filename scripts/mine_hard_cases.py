"""对抗难例挖掘：强模型出题 → 弱模型（Agent v1）探测 → 挑选 → 导出人工标注表。

  python scripts/mine_hard_cases.py generate   # deepseek-v4-pro 为每个卖家出题
  python scripts/mine_hard_cases.py probe      # Agent v1 每条跑 3 次
  python scripts/mine_hard_cases.py select     # 挑选并导出 data/hard/to-label.csv

产物在 data/hard/：
  candidates.jsonl   出题结果（含出题方预期标签，标注前不要看）
  probed.jsonl       加上 Agent 的 3 次结果（标注前不要看）
  to-label.csv       供人工盲标，只有帖子和评论，顺序已打乱
"""
from __future__ import annotations

import csv
import json
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.agent import POSTS, CommentAgent, extract_json  # noqa: E402
from agent.catalog import load_seller  # noqa: E402
from agent.llm import ROOT, LLMClient, load_config  # noqa: E402
from validate_dataset import load_rows  # noqa: E402

HARD_DIR = ROOT / "data" / "hard"
SELLERS = ["machinery", "adhesives", "textiles", "energy"]
PER_SELLER, MIN_PER_LABEL = 40, 8
PROBE_ATTEMPTS = 3
TARGET = 80
SEED = 20261115
LABELS = {"high", "medium", "low", "spam"}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def generate() -> None:
    cfg = load_config()
    llm = LLMClient(cfg)
    template = (ROOT / "evals" / "prompts" / "hard_case_generator.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "labeling-guide.md").read_text(encoding="utf-8")
    existing = load_rows()
    existing_texts = {r["comment"].strip().lower() for r in existing}

    def one(seller_id: str) -> list[dict]:
        posts = {k: v["text"] for k, v in POSTS.items() if v["seller_id"] == seller_id}
        prompt = template.format(
            labeling_guide=guide,
            seller_json=json.dumps(load_seller(seller_id), ensure_ascii=False, indent=1),
            posts="\n".join(f"- {k}: {v}" for k, v in posts.items()),
            existing="\n".join(f"- {r['comment']}" for r in existing if r["seller_id"] == seller_id),
            n=PER_SELLER, min_per_label=MIN_PER_LABEL,
        )
        out = llm.chat(model=cfg["judge"]["model"], messages=[{"role": "user", "content": prompt}],
                       max_tokens=32000, temperature=0.9, response_format={"type": "json_object"})
        items = extract_json(out.message["content"])["items"]
        kept = []
        for it in items:
            ok = (it.get("post_id") in posts and it.get("intended_label") in LABELS
                  and it.get("comment", "").strip().lower() not in existing_texts)
            if ok:
                kept.append({"seller_id": seller_id, **it})
        print(f"{seller_id}: 生成 {len(items)} 条，可用 {len(kept)} 条，用量 {out.usage.get('total_tokens')}")
        return kept

    with ThreadPoolExecutor(len(SELLERS)) as pool:
        batches = list(pool.map(one, SELLERS))
    rows = [r for b in batches for r in b]
    for i, r in enumerate(rows, 1):
        r["cid"] = f"c{i:03d}"
    write_jsonl(HARD_DIR / "candidates.jsonl", rows)
    print("预期标签分布:", Counter(r["intended_label"] for r in rows))
    print("难点分布:", Counter(r["hard_type"] for r in rows))


def probe() -> None:
    cfg = load_config()
    agent = CommentAgent(LLMClient(cfg), cfg, prompt_version="v1")
    rows = read_jsonl(HARD_DIR / "candidates.jsonl")
    jobs = [(r, a) for r in rows for a in range(PROBE_ATTEMPTS)]

    def run(job):
        r, a = job
        sample = {"id": r["cid"], **{k: r[k] for k in ("seller_id", "platform", "post_id", "comment")}}
        res = agent.run(sample, attempt=a)
        if res.error:  # 接口或运行错误：基础设施问题，要重跑
            return r["cid"], f"ERROR:{res.error}"
        if res.parse_error:  # 输出不是合法 JSON：Agent 自身的失败，算有效探测结果
            return r["cid"], "invalid"
        return r["cid"], res.parsed["label"]

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(run, jobs))
    by_cid: dict[str, list[str]] = {}
    for cid, label in results:
        by_cid.setdefault(cid, []).append(label)
    for r in rows:
        r["probe_labels"] = by_cid[r["cid"]]
    write_jsonl(HARD_DIR / "probed.jsonl", rows)
    errors = [l for r in rows for l in r["probe_labels"] if l.startswith("ERROR")]
    if errors:
        print(f"探测有 {len(errors)} 次调用报错，示例：{errors[0][:200]}")
        print("报错的调用不会写入缓存，排除问题后重跑 probe 即可，只会补跑失败的部分")
        return
    disagree = sum(any(l != r["intended_label"] for l in r["probe_labels"]) for r in rows)
    print(f"探测完成：{len(rows)} 条，其中 Agent 至少一次与出题方预期不一致 {disagree} 条")


def select() -> None:
    rows = read_jsonl(HARD_DIR / "probed.jsonl")
    if any(l.startswith("ERROR") for r in rows for l in r["probe_labels"]):
        sys.exit("probed.jsonl 里有报错的探测结果，报错会被误当成「不一致」，先重跑 probe 直到没有报错")
    for r in rows:
        labels = r["probe_labels"]
        r["n_disagree"] = sum(l != r["intended_label"] for l in labels)
        r["unstable"] = len(set(labels)) > 1
    flagged = [r for r in rows if r["n_disagree"] or r["unstable"]]
    rest = [r for r in rows if r not in flagged]
    rng = random.Random(SEED)
    flagged.sort(key=lambda r: (-r["n_disagree"], -r["unstable"]))
    chosen = flagged[:TARGET]
    fill = rng.sample(rest, min(len(rest), max(0, TARGET - len(chosen))))
    for r in chosen:
        r["selected_by"] = "flagged"
    for r in fill:
        r["selected_by"] = "random"
    picked = chosen + fill
    rng.shuffle(picked)
    for i, r in enumerate(picked, 1):
        r["id"] = f"h{i:03d}"
    write_jsonl(HARD_DIR / "selected.jsonl", picked)

    with (HARD_DIR / "to-label.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "post", "comment", "label", "uncertain", "note"])
        for r in picked:
            w.writerow([r["id"], POSTS[r["post_id"]]["text"], r["comment"], "", "", ""])
    print(f"候选 {len(rows)} 条，被标记 {len(flagged)} 条；选入 {len(chosen)} 条标记 + {len(fill)} 条随机 = {len(picked)} 条")
    print("已导出 data/hard/to-label.csv")


if __name__ == "__main__":
    {"generate": generate, "probe": probe, "select": select}[sys.argv[1]]()
