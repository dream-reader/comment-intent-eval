"""模型调用：OpenAI 兼容接口 + 本地 SQLite 缓存 + 重试。

缓存键 = 模型、消息、工具、参数、attempt 的哈希。
同一条样本做稳定性测试时用不同的 attempt，避免直接命中缓存。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI, RateLimitError

ROOT = Path(__file__).resolve().parents[1]
RETRYABLE = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)


def load_config() -> dict:
    load_dotenv(ROOT / ".env")
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@dataclass
class ChatResult:
    message: dict                      # role/content/reasoning_content/tool_calls
    finish_reason: str
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0
    cached: bool = False


class LLMClient:
    def __init__(self, cfg: dict | None = None, cache_path: Path | None = None):
        cfg = cfg or load_config()
        self.client = OpenAI(
            api_key=os.environ[cfg["api_key_env"]],
            base_url=os.environ.get(cfg["base_url_env"]) or "https://api.deepseek.com",
            timeout=180,
        )
        self.cache_path = cache_path or ROOT / "cache" / "llm.sqlite"
        self.cache_path.parent.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT)")

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.cache_path, timeout=30)

    def chat(self, *, model: str, messages: list[dict], tools: list[dict] | None = None,
             max_tokens: int, temperature: float, attempt: int = 0,
             response_format: dict | None = None, use_cache: bool = True) -> ChatResult:
        params = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
        if tools:
            params["tools"] = tools
        if response_format:
            params["response_format"] = response_format
        key = hashlib.sha256(
            json.dumps({**params, "attempt": attempt}, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

        if use_cache:
            with self._lock, self._db() as db:
                row = db.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
            if row:
                return ChatResult(**json.loads(row[0]), cached=True)

        result = self._call_with_retry(params)
        if use_cache and result.finish_reason in {"stop", "tool_calls"}:
            value = json.dumps({k: v for k, v in result.__dict__.items() if k != "cached"}, ensure_ascii=False)
            with self._lock, self._db() as db:
                db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?)", (key, value))
        return result

    def _call_with_retry(self, params: dict, retries: int = 4) -> ChatResult:
        for i in range(retries + 1):
            try:
                t0 = time.time()
                resp = self.client.chat.completions.create(**params)
                latency = time.time() - t0
                break
            except RETRYABLE:
                if i == retries:
                    raise
                time.sleep(2 ** i)
        choice = resp.choices[0]
        msg = choice.message
        message = {"role": "assistant", "content": msg.content or ""}
        reasoning = (msg.model_extra or {}).get("reasoning_content")
        if reasoning:
            message["reasoning_content"] = reasoning
        if msg.tool_calls:
            message["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ]
        usage = resp.usage.model_dump() if resp.usage else {}
        return ChatResult(message=message, finish_reason=choice.finish_reason, usage=usage, latency_s=latency)
