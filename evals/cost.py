"""按 config.yaml 里的价格把 token 用量折算成人民币（空闲时段价格）。"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PRICING = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))["pricing"]


def record_cost(record: dict, model: str) -> float:
    """单条运行记录的花费（元）。缓存命中数缺失时按全部未命中计，偏保守。"""
    p = PRICING[model]
    u = record["usage"]
    hit = u.get("cache_hit_tokens", 0)
    miss = u["prompt_tokens"] - hit
    return (hit * p["input_cache_hit"] + miss * p["input_cache_miss"] + u["completion_tokens"] * p["output"]) / 1e6
