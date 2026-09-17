"""Scrapling 抓取层（tg-scraper 插件等价实现）

对应 spec FR-15、NFR-7、NFR-8。

设计：
- 封装 Scrapling 的 StealthFetcher / PlayWrightFetcher（可选）
- 并发控制：asyncio.Semaphore(4)，单域名 ≤2，请求间最小间隔 500ms
- 遵守 robots.txt
- 失败降级：3 次重试后记录 error，不阻塞整体流程
- 输出统一格式：{url, title, fields, raw_html_excerpt, extracted, source_url}

注：Scrapling SDK 可能在沙箱内不可用（Playwright/Chromium 装不上）；
本模块在 import 失败时降级为 httpx + bs4 的轻量抓取，保证流水线仍可运行。
"""
from __future__ import annotations
import asyncio
import re
import time
import urllib.robotparser
from collections import defaultdict
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

# Scrapling 可选导入
try:
    from scrapling import StealthFetcher, PlayWrightFetcher  # type: ignore
    _SCRAPLING_OK = True
except ImportError:
    _SCRAPLING_OK = False

# 全局并发控制
_SEM_GLOBAL = asyncio.Semaphore(4)
_DOMAIN_SEM: Dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(2))
_LAST_REQUEST_TS: Dict[str, float] = defaultdict(float)
_MIN_INTERVAL = 0.5  # 单域名最小间隔秒
_TIMEOUT = 15.0
_MAX_RETRIES = 3

# robots.txt 缓存
_ROBOTS_CACHE: Dict[str, urllib.robotparser.RobotFileParser] = {}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc
    except Exception:
        return url


def _robots_allowed(url: str, user_agent: str = "*") -> bool:
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _ROBOTS_CACHE:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{base}/robots.txt")
        try:
            rp.read()
        except Exception:
            # 读不到 robots 默认允许（但仍受速率限制）
            _ROBOTS_CACHE[base] = None  # type: ignore
            return True
        _ROBOTS_CACHE[base] = rp
    rp = _ROBOTS_CACHE[base]
    if rp is None:
        return True
    try:
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


async def _rate_limit(domain: str) -> None:
    """单域名最小间隔。"""
    now = time.time()
    last = _LAST_REQUEST_TS[domain]
    delta = now - last
    if delta < _MIN_INTERVAL:
        await asyncio.sleep(_MIN_INTERVAL - delta)
    _LAST_REQUEST_TS[domain] = time.time()


async def _fetch_with_scrapling(url: str, *, render_js: bool = False) -> Dict[str, Any]:
    """用 Scrapling 抓取。返回原始 fetcher 对象的 dict 化结果。"""
    fetcher = PlayWrightFetcher if render_js else StealthFetcher
    # Scrapling API：fetch(url) 返回 AdaptiveElement，可 .css_first() 等
    # 本层做最小封装，向上层暴露统一 dict
    page = await asyncio.to_thread(fetcher.get, url) if hasattr(fetcher, "get") else None
    if page is None:
        # async 接口
        page = await fetcher.async_fetch(url) if hasattr(fetcher, "async_fetch") else None
    if page is None:
        raise RuntimeError(f"Scrapling 未返回页面：{url}")
    title = ""
    try:
        title = page.css_first("title").text  # type: ignore
    except Exception:
        pass
    text = ""
    try:
        text = page.get_all_text()  # type: ignore
    except Exception:
        try:
            text = page.css("body::text").get()  # type: ignore
        except Exception:
            text = ""
    return {
        "url": url,
        "title": title or "",
        "text": text[:8000],
        "html_excerpt": "",
    }


async def _fetch_with_httpx(url: str) -> Dict[str, Any]:
    """降级抓取：优先 curl 子进程（沙箱内对 https+代理更可靠），失败回退 httpx。"""
    text = await _fetch_via_curl(url)
    if text is None:
        # 回退 httpx（trust_env 读环境代理）
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, trust_env=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; TravelGuideBot/1.0; +https://example.com/bot)"
            })
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {url}")
        text = resp.text
    # bs4 抽标题与正文
    title = ""
    body_text = text
    try:
        from bs4 import BeautifulSoup  # type: ignore
        soup = BeautifulSoup(text, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        # 简单正文抽取：移除 script/style/nav
        for sel in ("script", "style", "nav", "header", "footer"):
            for tag in soup.find_all(sel):
                tag.decompose()
        body_text = soup.get_text(separator=" ", strip=True)
    except ImportError:
        pass
    return {
        "url": url,
        "title": title,
        "text": body_text[:8000],
        "html_excerpt": text[:2000],
    }


async def _fetch_via_curl(url: str) -> "Optional[str]":
    """用 curl 子进程抓取（沙箱内 curl 对 https+代理支持更好）。"""
    import asyncio
    import shutil
    if not shutil.which("curl"):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sSL", "--max-time", str(int(_TIMEOUT)),
            "-A", "Mozilla/5.0 (compatible; TravelGuideBot/1.0)",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT + 5)
        if proc.returncode != 0 or not stdout:
            return None
        # wikipedia utf-8
        try:
            return stdout.decode("utf-8")
        except UnicodeDecodeError:
            return stdout.decode("utf-8", errors="replace")
    except Exception:
        return None


async def scrape_one(task: Dict[str, Any]) -> Dict[str, Any]:
    """抓取单条任务。task 字段：target_url/source_type/query/fields。

    返回：{url, title, fields, raw_html_excerpt, extracted, source_url, error?}
    """
    url = task.get("target_url") or ""
    source_type = task.get("source_type", "generic")
    query = task.get("query", "")
    fields = task.get("fields", [])

    if not url:
        # 没有具体 URL，仅用 query 作为搜索词；v1 不实现站内搜索，直接返回空
        return {"url": "", "title": query, "extracted": {}, "source_url": "",
                "fields": fields, "raw_html_excerpt": "", "source_type": source_type,
                "note": "no_target_url_skip_search"}

    if not _robots_allowed(url):
        return {"url": url, "title": "", "extracted": {}, "source_url": url,
                "fields": fields, "raw_html_excerpt": "",
                "source_type": source_type, "error": "robots_disallowed"}

    domain = _domain(url)
    last_err = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with _SEM_GLOBAL, _DOMAIN_SEM[domain]:
                await _rate_limit(domain)
                if _SCRAPLING_OK:
                    raw = await _fetch_with_scrapling(url, render_js=source_type == "generic")
                else:
                    raw = await _fetch_with_httpx(url)
            extracted = _extract_fields(raw.get("text", ""), fields, source_type, query)
            return {
                "url": url, "title": raw.get("title", ""),
                "extracted": extracted,
                "source_url": url, "source_type": source_type,
                "fields": fields,
                "raw_html_excerpt": raw.get("html_excerpt", "")[:1500],
            }
        except Exception as e:
            last_err = e
            await asyncio.sleep(0.5 * attempt)
    return {"url": url, "title": "", "extracted": {},
            "source_url": url, "source_type": source_type,
            "fields": fields, "raw_html_excerpt": "",
            "error": f"retries_exhausted: {last_err}"}


def _extract_fields(text: str, fields: List[str], source_type: str, query: str) -> Dict[str, Any]:
    """从正文中抽取目标字段。v1 用简单关键词匹配，后续可接 LLM 抽取。"""
    out: Dict[str, Any] = {"query": query}
    if not text:
        return out
    # 简单策略：找包含 query 的句子作为 desc
    sentences = re.split(r"[。\.!\?！？\n]", text)
    relevant = [s.strip() for s in sentences if query in s]
    out["desc"] = relevant[0][:300] if relevant else text[:300]
    # 票价：粗匹配"门票 ¥XX / XX元"
    m = re.search(r"(门票|票价)[^0-9]{0,5}(\d+(?:-\d+)?)\s*(?:元|¥)?", text)
    if m:
        out["ticket"] = m.group(0)
    return out


async def batch(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """并发抓取多条任务。

    返回 {materials: [...], sources: [{url,title}]}。
    """
    if not tasks:
        return {"materials": [], "sources": []}
    results = await asyncio.gather(*[scrape_one(t) for t in tasks], return_exceptions=True)
    materials: List[Dict[str, Any]] = []
    sources: List[Dict[str, str]] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        if r.get("error"):
            continue
        materials.append(r)
        if r.get("source_url"):
            sources.append({"url": r["source_url"], "title": r.get("title", "")})
    return {"materials": materials, "sources": sources}
