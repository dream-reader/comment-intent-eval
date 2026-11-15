"""卖家产品目录与 lookup_product 工具。"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "lookup_product",
        "description": (
            "查询卖家的产品目录，返回匹配产品的型号、规格、认证、起订量，以及卖家的发货范围和付款方式。"
            "评论涉及产品、规格、认证、起订量、发货或付款时先调用。目录里没有的信息不能写进回复。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "产品型号、名称或属性关键词（英文），例如 VF420、sealant、softshell；传 * 返回全部产品",
                }
            },
            "required": ["keyword"],
        },
    },
}


@lru_cache
def load_seller(seller_id: str) -> dict:
    return json.loads((ROOT / "data" / "sellers" / f"{seller_id}.json").read_text(encoding="utf-8"))


def _text_of(product: dict) -> str:
    return json.dumps(product, ensure_ascii=False).lower()


def lookup_product(seller_id: str, keyword: str) -> dict:
    """按关键词匹配产品：任一关键词出现在产品的任意字段中即命中。"""
    seller = load_seller(seller_id)
    products = seller["products"]
    words = [w for w in re.split(r"[\s,/]+", keyword.lower()) if len(w) >= 2]
    if keyword.strip() == "*" or not words:
        matches = products
    else:
        matches = [p for p in products if any(w in _text_of(p) for w in words)]
    result = {
        "company": seller["company"],
        "ships_to": seller.get("ships_to", []),
        "payment_terms": seller.get("payment_terms", []),
        "matches": matches,
    }
    for extra in ("samples", "unit_notes"):
        if extra in seller:
            result[extra] = seller[extra]
    if not matches:
        result["note"] = "目录中没有匹配的产品。不要编造型号或规格；可以用 * 查看全部产品。"
    return result
