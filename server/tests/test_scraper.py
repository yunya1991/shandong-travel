"""Scrapling 抓取层冒烟测试（对应 Task 14 / TR-14.1, TR-14.2）

跑法：
    cd server && .venv/bin/python -m tests.test_scraper

设计：TR-14.1 用沙箱内可访问的 example.com 验证抓取链路通；
若环境能访问中文 Wikipedia（生产环境）则补跑趵突泉用例。
TR-14.2 用不存在的 URL 验证重试与 error 降级。
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import scraper  # noqa: E402


async def test_basic_extraction():
    # TR-14.1：对可访问页面抓取返回非空 extracted
    task = {
        "target_url": "https://example.com",
        "source_type": "generic",
        "query": "Example",
        "fields": ["name", "desc"],
    }
    res = await scraper.scrape_one(task)
    print("[TR-14.1] result keys:", list(res.keys()))
    print("[TR-14.1] title:", res.get("title", "")[:80])
    print("[TR-14.1] extracted.desc head:", res.get("extracted", {}).get("desc", "")[:80])
    assert not res.get("error"), f"error: {res.get('error')}"
    assert res.get("extracted", {}).get("desc"), "extracted.desc 为空"
    print("[TR-14.1] PASSED\n")


async def test_invalid_url_retries():
    # TR-14.2：对不存在的 URL 重试 3 次后返回 {error}
    task = {
        "target_url": "https://example.invalid.localhost.fake/page-not-exist",
        "source_type": "generic",
        "query": "test",
        "fields": ["name"],
    }
    res = await scraper.scrape_one(task)
    print("[TR-14.2] error:", res.get("error"))
    assert res.get("error"), "应返回 error 字段"
    assert "retries_exhausted" in res["error"], f"错误信息不符：{res['error']}"
    print("[TR-14.2] PASSED\n")


async def _optional_wikipedia():
    """可选：若环境能访问中文 Wikipedia，补趵突泉用例。"""
    task = {
        "target_url": "https://zh.wikipedia.org/wiki/趵突泉",
        "source_type": "wikipedia",
        "query": "趵突泉",
        "fields": ["name", "desc"],
    }
    try:
        res = await scraper.scrape_one(task)
    except Exception as e:
        print(f"[wikipedia optional] skipped: {e}")
        return
    if res.get("error"):
        print(f"[wikipedia optional] skipped: {res['error']}")
        return
    print("[wikipedia optional] title:", res.get("title", "")[:80])
    print("[wikipedia optional] PASSED\n")


async def main():
    await test_basic_extraction()
    await test_invalid_url_retries()
    await _optional_wikipedia()
    print("All Task 14 tests PASSED")


if __name__ == "__main__":
    asyncio.run(main())
