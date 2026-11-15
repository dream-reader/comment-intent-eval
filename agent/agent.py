"""评论意向分级 Agent：工具调用循环 + 最终 JSON 输出。

Agent 只负责产出结果和运行痕迹（原始输出、工具调用、用量、耗时），
不做任何质量判断；判断全部交给 evals/。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ValidationError

from .catalog import TOOL_SPEC, load_seller, lookup_product
from .llm import ROOT, LLMClient

MAX_TOOL_ROUNDS = 3
PLATFORMS = yaml.safe_load((ROOT / "data" / "platforms.yaml").read_text(encoding="utf-8"))
POSTS = json.loads((ROOT / "data" / "posts.json").read_text(encoding="utf-8"))


class AgentOutput(BaseModel):
    label: Literal["high", "medium", "low", "spam"]
    signals: list[str]
    reason: str
    language: str
    reply: str


@dataclass
class AgentResult:
    id: str
    attempt: int
    prompt_version: str
    model: str
    raw_content: str = ""
    parsed: dict | None = None
    parse_error: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    turns: int = 0
    usage: dict = field(default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0})
    latency_s: float = 0.0
    cached: bool = False
    error: str | None = None


def load_prompt(version: str) -> str:
    return (ROOT / "agent" / "prompts" / f"{version}.md").read_text(encoding="utf-8")


def build_user_message(sample: dict) -> str:
    seller = load_seller(sample["seller_id"])
    limit = PLATFORMS[sample["platform"]]["max_chars"]
    return (
        f"企业：{seller['company']}（{seller['industry']}）\n"
        f"平台：{sample['platform']}，回复字数上限 {limit} 字符\n"
        f"帖子：{POSTS[sample['post_id']]['text']}\n"
        f"评论：<<<{sample['comment']}>>>"
    )


def extract_json(text: str) -> dict:
    """容忍 ```json 包裹和前后多余文字，取第一个完整 JSON 对象。"""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(candidate)


class CommentAgent:
    def __init__(self, llm: LLMClient, cfg: dict, prompt_version: str = "v1", model: str | None = None):
        self.llm = llm
        self.cfg = cfg["agent"]
        self.model = model or self.cfg["model"]
        self.prompt_version = prompt_version
        self.system_prompt = load_prompt(prompt_version)

    def run(self, sample: dict, attempt: int = 0) -> AgentResult:
        res = AgentResult(id=sample["id"], attempt=attempt, prompt_version=self.prompt_version, model=self.model)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": build_user_message(sample)},
        ]
        t0 = time.time()
        all_cached = True
        try:
            for _ in range(MAX_TOOL_ROUNDS + 1):
                out = self.llm.chat(
                    model=self.model, messages=messages, tools=[TOOL_SPEC],
                    max_tokens=self.cfg["max_tokens"], temperature=self.cfg["temperature"], attempt=attempt,
                )
                res.turns += 1
                all_cached &= out.cached
                self._add_usage(res, out.usage)
                messages.append(out.message)
                calls = out.message.get("tool_calls") or []
                if not calls:
                    res.raw_content = out.message.get("content", "")
                    if out.finish_reason != "stop":
                        res.error = f"finish_reason={out.finish_reason}"
                    break
                for call in calls:
                    messages.append(self._run_tool(sample, call, res))
            else:
                res.error = f"工具调用超过 {MAX_TOOL_ROUNDS} 轮"
        except Exception as e:  # noqa: BLE001 — 运行错误要记录下来，不能中断整批
            res.error = f"{type(e).__name__}: {e}"
        res.latency_s = round(time.time() - t0, 2)
        res.cached = all_cached and res.turns > 0
        if res.raw_content and not res.error:
            self._parse(res)
        return res

    def _run_tool(self, sample: dict, call: dict, res: AgentResult) -> dict:
        try:
            keyword = json.loads(call["function"]["arguments"]).get("keyword", "")
            result = lookup_product(sample["seller_id"], keyword)
        except (json.JSONDecodeError, KeyError) as e:
            keyword, result = None, {"error": f"参数错误：{e}"}
        res.tool_calls.append({"keyword": keyword, "matches": len(result.get("matches", []))})
        return {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)}

    @staticmethod
    def _add_usage(res: AgentResult, usage: dict) -> None:
        res.usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
        res.usage["completion_tokens"] += usage.get("completion_tokens", 0)
        details = usage.get("completion_tokens_details") or {}
        res.usage["reasoning_tokens"] += details.get("reasoning_tokens", 0) or 0

    @staticmethod
    def _parse(res: AgentResult) -> None:
        try:
            res.parsed = AgentOutput(**extract_json(res.raw_content)).model_dump()
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            res.parse_error = f"{type(e).__name__}: {str(e)[:300]}"


def to_record(res: AgentResult) -> dict:
    return asdict(res)
