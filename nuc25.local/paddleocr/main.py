import asyncio
import base64
import io
import json
import os
import time
import uuid
from typing import Optional

import httpx
import pypdfium2
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from openai import AsyncOpenAI

app = FastAPI(title="PaddleOCR API")

VLLM_BASE_URL = os.environ["OPENAI_API_BASE"]
VLLM_API_KEY  = os.environ.get("OPENAI_API_KEY", "dummy")
VLLM_MODEL    = os.environ["OPENAI_API_MODEL"]

client = AsyncOpenAI(
    base_url=VLLM_BASE_URL,
    api_key=VLLM_API_KEY,
    http_client=httpx.AsyncClient(
        transport=httpx.AsyncHTTPTransport(retries=1),
        timeout=httpx.Timeout(120.0),
    ),
)

OCR_PROMPT = (
    "Extract all text from this image exactly as it appears. "
    "Return only the extracted text, preserving layout where possible."
)

# In-memory job store: job_id -> {state, result, errorMsg, created_at}
_jobs: dict[str, dict] = {}
_JOB_TTL = 3600  # seconds

# How many pages to OCR concurrently per PDF. vLLM batches these via continuous
# batching, so raising this trades client/vLLM load for throughput. Env-tunable.
PAGE_CONCURRENCY = int(os.environ.get("PADDLEOCR_PAGE_CONCURRENCY", "8"))


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                f"{VLLM_BASE_URL.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
                timeout=5,
            )
            resp.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"backend unreachable: {exc}")
    return {"status": "ok", "model": VLLM_MODEL}


@app.get("/v1/models")
async def models():
    async with httpx.AsyncClient() as http:
        resp = await http.get(
            f"{VLLM_BASE_URL.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {VLLM_API_KEY}"},
            timeout=10,
        )
    return resp.json()


async def _ocr_one_page(img, sem: asyncio.Semaphore) -> str:
    """OCR a single rendered page image. Bounded by the shared semaphore."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64_img = base64.b64encode(buf.getvalue()).decode()
    async with sem:
        response = await client.chat.completions.create(
            model=VLLM_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}},
                        {"type": "text", "text": OCR_PROMPT},
                    ],
                }
            ],
            max_tokens=2048,
            temperature=0,
        )
    return response.choices[0].message.content or ""


async def _run_ocr_job(job_id: str, pdf_bytes: bytes) -> None:
    """Background task: render each PDF page and run VLM OCR."""
    try:
        pdf = pypdfium2.PdfDocument(pdf_bytes)
        page_images = []
        try:
            for i in range(len(pdf)):
                bitmap = pdf[i].render(scale=1.5)
                page_images.append(bitmap.to_pil())
        finally:
            pdf.close()

        if not page_images:
            _jobs[job_id].update({"state": "failed", "errorMsg": "PDF has no pages"})
            return

        # OCR pages concurrently (bounded) so vLLM can batch them via continuous
        # batching. gather preserves page order; a failing page yields a placeholder
        # so one bad page never fails the whole job.
        sem = asyncio.Semaphore(PAGE_CONCURRENCY)
        texts = await asyncio.gather(
            *(_ocr_one_page(img, sem) for img in page_images),
            return_exceptions=True,
        )

        layout_parsing_results = []
        for img, result in zip(page_images, texts):
            block_content = "[OCR failed]" if isinstance(result, Exception) else result.strip()
            layout_parsing_results.append({
                "prunedResult": {
                    "parsing_res_list": [
                        {
                            "block_content": block_content,
                            "block_label": "text",
                            "block_bbox": [0, 0, img.width, img.height],
                        }
                    ]
                }
            })

        _jobs[job_id].update({
            "state": "done",
            "result": {"layoutParsingResults": layout_parsing_results},
        })

    except Exception as exc:
        _jobs[job_id].update({"state": "failed", "errorMsg": str(exc)})


def _cleanup_old_jobs() -> None:
    now = time.monotonic()
    expired = [jid for jid, j in _jobs.items() if now - j["created_at"] > _JOB_TTL]
    for jid in expired:
        del _jobs[jid]


@app.post("/api/v2/ocr/jobs")
async def submit_ocr_job(
    file: UploadFile = File(...),
    model: str = Form(default="PaddleOCR-VL"),
    optionalPayload: Optional[str] = Form(default=None),
):
    """RAGFlow async OCR submit — multipart form upload."""
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(400, detail="empty file")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"state": "processing", "created_at": time.monotonic()}
    asyncio.create_task(_run_ocr_job(job_id, pdf_bytes))
    _cleanup_old_jobs()

    return {"errorCode": 0, "data": {"jobId": job_id}}


@app.get("/api/v2/ocr/jobs/{job_id}")
async def poll_ocr_job(request: Request, job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="job not found")

    state = job["state"]
    if state == "done":
        base = str(request.base_url).rstrip("/")
        return {"errorCode": 0, "data": {"state": "done", "resultJsonUrl": f"{base}/api/v2/ocr/jobs/{job_id}/result"}}
    if state == "failed":
        return {"errorCode": 1, "data": {"state": "failed", "errorMsg": job.get("errorMsg", "unknown error")}}
    return {"errorCode": 0, "data": {"state": "processing"}}


@app.get("/api/v2/ocr/jobs/{job_id}/result")
async def get_ocr_job_result(job_id: str):
    job = _jobs.get(job_id)
    if not job or job.get("state") != "done":
        raise HTTPException(404, detail="result not ready")

    return PlainTextResponse(
        content=json.dumps({"result": job["result"]}),
        media_type="application/x-ndjson",
    )
