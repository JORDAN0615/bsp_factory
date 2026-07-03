"""Web search fallback for CRAG.

When the knowledge-base contains no relevant documents, the agent falls
back to web search to find external resources (NVIDIA docs, kernel bugzilla,
Advantech support pages, etc.).

Uses aiohttp + BeautifulSoup for simple HTTP GET + HTML parsing.
In production replace with SerpAPI / Tavily / official search API.
"""

from __future__ import annotations

import re
from typing import Any

import aiohttp
from bs4 import BeautifulSoup

from rag.rag_state import AgentState

from rag_config import DEBUG_RETRIEVAL


def _safe_query_url(query: str) -> str:
    """URL-encode a search query safely."""
    from urllib.parse import quote_plus
    if not query:
        return "site:nvidia.com OR site:kernel.org OR site:advantech.com.tw BSP debug"
    return quote_plus(query)


async def search_web(query: str) -> list[dict[str, str]]:
    """Search the web and return top results with title/snippet."""
    safe_q = _safe_query_url(query)

    headers = {
        "User-Agent": (
            "MIC-BSP-Agent/1.0 (+https://example.com; "
            "langgraph-bsprag@example.com)"
        ),
    }

    results: list[dict[str, str]] = []
    urls_to_fallback = [
        f"https://www.google.com/search?q={safe_q}&num=10",
    ]

    for page_url in urls_to_fallback:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    page_url, headers=headers, timeout=15,
                ) as resp:
                    if resp.status != 200:
                        continue
                    text = await resp.text(errors="replace")
            soup = BeautifulSoup(text, "html.parser")

            # Extract search result blocks.
            for block in soup.find_all("div", class_=["Gx5Zad", "MjjYud"])[:5]:
                title_tag = block.find("a") or block.find("h3")
                snippet_tag = block.find("span", class_=["Vu7Db", "ydx35a"]) or block.find("div", class_="VwiC3b")

                title = title_tag.get_text(strip=True) if title_tag else ""
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
                url = title_tag.get("href", "") if title_tag else ""

                # Google wraps result URLs in /url?q=... strips leading /
                if url.startswith("/url?q="):
                    url = url[7:]  # strip /url?q=

                if title and snippet:
                    results.append({"title": title, "snippet": snippet, "url": url})

            if results:
                break  # found useful results

        except Exception:
            if DEBUG_RETRIEVAL:
                print(f"[WEB_SEARCH] failed to fetch: {page_url}")
            continue

    return results[:5]


def default_web_answer(query: str) -> str:
    """Default answer when web search is unavailable or returns nothing.

    This prevents the LLM from hallucinating when KB + web both fail.
    """
    return (
        f"知識庫和外部搜尋都找不到關於「{query}」的明確資訊。\n"
        "建議：\n"
        "1. 檢查 NVIDIA Developer Forums 或 kernel.org bugzilla\n"
        "2. 確認 BSP 版本與硬體平台是否匹配\n"
        "3. 查 dmesg / serial console 取得更精確的錯誤訊息"
    )


def _format_web_docs(web_docs: list[dict[str, str]], query: str) -> str:
    """Format web search results for the LLM prompt."""
    if not web_docs:
        return f"(無 web 搜尋結果，建議查 {query} 的官方文件)"
    blocks = []
    for i, doc in enumerate(web_docs, 1):
        blocks.append(
            f"[{i}] {doc['title']}\n    {doc['snippet']}\n    URL: {doc.get('url', 'N/A')}"
        )
    return "\n\n".join(blocks)


def _web_fallback_node(state: BSPState) -> BSPState:
    """Run web search with a coroutine runner."""
    import asyncio

    query = state["question"]
    web_docs = asyncio.run(search_web(query))

    if not web_docs:
        answer = default_web_answer(query)
    else:
        # Use LLM to synthesize web docs into an answer.
        context = _format_web_docs(web_docs, query)
        try:
            from llm.service import chat
            prompt = f"""你是 MIC BSP 除錯助手。以下是 web 搜尋找到的相關資料，請整合並回答。
若搜尋結果也不足以回答，請明確說明。

Web Search Context:
{context}

Question: {query}

回答要求：
- 使用繁體中文
- 標註搜尋結果來源 (標題或 URL)
- 簡潔列出排查步驟或原因
"""
            answer = chat(prompt)
        except Exception:
            answer = default_web_answer(query)

    if DEBUG_RETRIEVAL:
        print(f"\n[WEB_FALLBACK] fetched {len(web_docs)} docs\n")

    return {
        "web_docs": web_docs,
        "source": "web" if web_docs else "unknown",
        "answer": answer,
    }

