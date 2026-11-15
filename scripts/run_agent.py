"""在评测集上批量运行 Agent，结果写入 reports/runs/<run_name>/。

用法：
  python scripts/run_agent.py --prompt v1                 # 基础集全量
  python scripts/run_agent.py --prompt v1 --split hard    # 难例集全量
  python scripts/run_agent.py --prompt v1 --limit 5       # 试跑前 5 条
  python scripts/run_agent.py --ids m001,a013 --attempts 3
  python scripts/run_agent.py --prompt v1 --model deepseek-v4-pro --name v1-pro
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.agent import CommentAgent, load_prompt, to_record  # noqa: E402
from agent.llm import ROOT, LLMClient, load_config  # noqa: E402
from validate_dataset import load_rows  # noqa: E402


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="v1")
    ap.add_argument("--split", default="base", choices=["base", "hard", "holdout"], help="评测集：base 基础集 / hard 难例集 / holdout 留出集")
    ap.add_argument("--model")
    ap.add_argument("--ids", help="逗号分隔的样本 id")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--attempts", type=int, default=1, help="每条样本运行次数（稳定性测试用）")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--name", help="运行名称，默认 <prompt>-<model>")
    args = ap.parse_args()

    cfg = load_config()
    agent = CommentAgent(LLMClient(cfg), cfg, prompt_version=args.prompt, model=args.model)
    samples = [{k: v for k, v in r.items() if k != "_where"} for r in load_rows(args.split)]
    if args.ids:
        wanted = set(args.ids.split(","))
        samples = [s for s in samples if s["id"] in wanted]
    if args.limit:
        samples = samples[: args.limit]

    name = args.name or f"{args.split}-{args.prompt}-{agent.model}"
    out_dir = ROOT / "reports" / "runs" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [(s, a) for s in samples for a in range(args.attempts)]
    print(f"运行 {name}：{len(samples)} 条样本 × {args.attempts} 次 = {len(jobs)} 次")

    t0 = time.time()
    records = []
    with ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(agent.run, s, a) for s, a in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            records.append(to_record(fut.result()))
            if i % 20 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}")
    records.sort(key=lambda r: (r["id"], r["attempt"]))

    with (out_dir / "outputs.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    errors = [r for r in records if r["error"]]
    parse_errors = [r for r in records if r["parse_error"]]
    meta = {
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "split": args.split,
        "prompt_version": args.prompt,
        "prompt_sha256": hashlib.sha256(load_prompt(args.prompt).encode()).hexdigest()[:12],
        "model": agent.model,
        "agent_config": cfg["agent"],
        "samples": len(samples),
        "attempts": args.attempts,
        "wall_time_s": round(time.time() - t0, 1),
        "run_errors": len(errors),
        "parse_errors": len(parse_errors),
        "cached_runs": sum(r["cached"] for r in records),
        "tokens": {k: sum(r["usage"][k] for r in records) for k in ("prompt_tokens", "cache_hit_tokens", "completion_tokens", "reasoning_tokens")},
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))
    for r in errors[:5]:
        print("运行错误:", r["id"], r["error"])
    for r in parse_errors[:5]:
        print("解析失败:", r["id"], r["parse_error"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
