from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from spider_rs import Website

app = FastAPI(title="Local Spider Crawler")

class CrawlRequest(BaseModel):
    url: str = Field(..., min_length=1)
    limit: Optional[int] = Field(10, ge=1, le=100)
    render_js: Optional[bool] = Field(False)

class PageResult(BaseModel):
    url: str
    title: Optional[str] = ""
    text: Optional[str] = ""
    links: List[str] = []

@app.get("/health")
async def health():
    return {"status": "ok", "engine": "spider-rs"}

@app.post("/crawl", response_model=List[PageResult])
async def crawl(req: CrawlRequest):
    try:
        # scrape() (not crawl()) is what retains page content for get_pages();
        # crawl() only collects links. with_budget bounds the crawl to `limit`
        # pages so we don't scrape an entire large site.
        website = (
            Website(req.url)
            .with_budget({"*": req.limit})
            .with_return_page_links(True)
        )
        website.scrape()
        results = []
        for page in website.get_pages():
            # spider_rs Page exposes url/content/links as properties and
            # title() as a method. `content` is the page HTML.
            text = page.content or ""
            # Skip pages with no extractable content (e.g. an unreachable host
            # still yields a seed page with empty content) so we don't ingest
            # empty documents downstream. `limit` applies to non-empty pages.
            if not text.strip():
                continue
            results.append(PageResult(
                url=page.url or "",
                title=(page.title() or "").strip(),
                text=text,
                links=sorted(page.links or []),
            ))
            if len(results) >= req.limit:
                break
        return results
    except Exception as e:
        raise HTTPException(500, detail=str(e))
