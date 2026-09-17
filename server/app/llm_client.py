"""OpenAI 兼容 LLM 调用客户端

作为 DSH 不可用时的回退引擎（spec NFR-8 降级）。
DSH 可用时由 dsh_runner 路由到对应 provider，本模块不参与。
"""
from __future__ import annotations
import json
import os
from typing import Any, Dict, Optional

import httpx


async def chat_completion(
    messages: list,
    *,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int = 8192,
    temperature: float = 0.4,
    response_format_json: bool = False,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """调用 OpenAI 兼容 /chat/completions。

    response_format_json=True 时强制 JSON 输出（DeepSeek/OpenAI 均支持）。
    返回 dict：若解析为 JSON 则返回对象，否则返回 {"_raw": str}。
    """
    url = f"{base_url.rstrip('/')}/chat/completions"
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format_json:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    # 强制提取 JSON（容错：模型有时包 ```json ... ```）
    if response_format_json or _looks_json(content):
        parsed = _extract_json(content)
        if parsed is not None:
            return parsed
    return {"_raw": content}


def _looks_json(s: str) -> bool:
    s = s.strip().lower()
    return s.startswith("{") or s.startswith("[")


def _extract_json(s: str) -> Optional[Any]:
    s = s.strip()
    if s.startswith("```"):
        # 去掉 markdown code fence
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        # 尝试找到首个 { 或 [ 到末尾
        start = -1
        for ch in ("{", "["):
            i = s.find(ch)
            if i != -1 and (start == -1 or i < start):
                start = i
        if start == -1:
            return None
        for end in range(len(s), start, -1):
            try:
                return json.loads(s[start:end])
            except json.JSONDecodeError:
                continue
        return None


async def generate_plan_via_llm(
    destination: str,
    prefs: Dict[str, Any],
    *,
    base_url: str,
    api_key: str,
    model: str,
    materials: Optional[list] = None,
) -> Dict[str, Any]:
    """降级模式：直接用 LLM 生成 plan（不走 DSH）。"""
    from .prompts import SYSTEM_PROMPT, INTEGRATE_PLAN
    materials = materials or []
    user_prompt = INTEGRATE_PLAN.format(
        destination=destination,
        prefs=json.dumps(prefs, ensure_ascii=False),
        materials=json.dumps(materials, ensure_ascii=False),
    )
    return await chat_completion(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_tokens=12000,
        temperature=0.45,
        response_format_json=True,
    )
