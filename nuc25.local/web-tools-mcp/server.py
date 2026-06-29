"""MCP server exposing web tools to the RAGFlow agent.

Provides two tools over the streamable-HTTP transport (served at /mcp):

  - web_search : live web search via the SearXNG JSON API
  - crawl      : on-demand site crawling via the spider-local service

Both upstream services run on the same `ragflow` Docker network and are
reached by their container DNS names. Override via SEARXNG_URL / SPIDER_URL.
"""
import atexit
import os

import httpx
from langfuse import get_client, observe
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080").rstrip("/")
SPIDER_URL = os.environ.get("SPIDER_URL", "http://spider-local:8000").rstrip("/")

# Initialise the singleton Langfuse client — it reads LANGFUSE_PUBLIC_KEY,
# LANGFUSE_SECRET_KEY, and LANGFUSE_HOST from the environment.
_lf = get_client()
atexit.register(_lf.flush)

mcp = FastMCP("rag-web-tools", host="0.0.0.0", port=8000)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp.tool()
@observe(name="rag-mcp.web_search", as_type="tool")
def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web via SearXNG and return the top result snippets.

    Args:
        query: The search query.
        max_results: Maximum number of results to return (default 5).

    Returns:
        A list of {title, url, content} dicts.
    """
    lf = get_client()
    lf.update_current_span(
        input={"query": query, "max_results": max_results},
        metadata={"searxng_url": SEARXNG_URL},
    )
    resp = httpx.get(
        f"{SEARXNG_URL}/search",
        params={"q": query, "format": "json"},
        timeout=30.0,
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    output = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
        }
        for r in results[:max_results]
    ]
    lf.update_current_span(output={"result_count": len(output), "results": output})
    return output


@mcp.tool()
@observe(name="rag-mcp.crawl", as_type="tool")
def crawl(url: str, limit: int = 10, render_js: bool = False) -> list[dict]:
    """Crawl a website starting at `url` and return the extracted page text.

    Args:
        url: The start URL to crawl.
        limit: Maximum number of pages to return (1-100, default 10).
        render_js: Render JavaScript before extracting text (default False).

    Returns:
        A list of {url, title, text} dicts, one per crawled page.
    """
    lf = get_client()
    lf.update_current_span(
        input={"url": url, "limit": limit, "render_js": render_js},
        metadata={"spider_url": SPIDER_URL},
    )
    resp = httpx.post(
        f"{SPIDER_URL}/crawl",
        json={"url": url, "limit": limit, "render_js": render_js},
        timeout=300.0,
    )
    resp.raise_for_status()
    pages = resp.json()
    output = [
        {
            "url": p.get("url", ""),
            "title": p.get("title", ""),
            "text": p.get("text", ""),
        }
        for p in pages
    ]
    lf.update_current_span(output={"page_count": len(output), "pages": output})
    return output


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
