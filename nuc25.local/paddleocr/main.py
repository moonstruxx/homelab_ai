import asyncio
import base64
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import PlainTextResponse
from langfuse import get_client

BACKEND_URL = os.environ["PADDLEOCR_BACKEND_URL"].rstrip("/")
REQUEST_TIMEOUT = float(os.environ.get("PADDLEOCR_REQUEST_TIMEOUT", "10800"))

# Initialise the singleton client; reads LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY,
# LANGFUSE_HOST from environment.
_lf = get_client()

# In-memory job store: job_id -> {state, result, errorMsg, created_at}
_jobs: dict[str, dict] = {}
_JOB_TTL = 3600  # seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _lf.flush()


app = FastAPI(title="PaddleOCR Proxy", lifespan=lifespan)


@app.get("/health")
async def health():
    try:
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{BACKEND_URL}/health", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            if data.get("errorCode") != 0:
                raise ValueError(data.get("errorMsg", "unhealthy"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"backend unreachable: {exc}")
    return {"status": "ok", "backend": BACKEND_URL}


def _file_type(data: bytes) -> int:
    """Detect file type from magic bytes: 0=PDF, 1=image."""
    return 0 if data[:4] == b"%PDF" else 1


async def _run_ocr_job(job_id: str, file_bytes: bytes) -> None:
    """Background task: forward to tp42's synchronous /layout-parsing."""
    file_type = _file_type(file_bytes)
    file_type_name = "pdf" if file_type == 0 else "image"

    with _lf.start_as_current_observation(
        name="paddleocr.job",
        as_type="agent",
        input={"job_id": job_id, "file_size_bytes": len(file_bytes), "file_type": file_type_name},
    ):
        with _lf.start_as_current_observation(
            name="tp42.layout_parsing",
            as_type="span",
            input={"backend_url": BACKEND_URL, "file_type": file_type},
        ) as span:
            try:
                file_b64 = base64.b64encode(file_bytes).decode()
                payload = {"file": file_b64, "fileType": file_type}

                async with httpx.AsyncClient() as http:
                    resp = await http.post(
                        f"{BACKEND_URL}/layout-parsing",
                        content=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"},
                        timeout=REQUEST_TIMEOUT,
                    )

                if resp.status_code != 200:
                    msg = f"HTTP {resp.status_code}: {resp.text}"
                    span.update(level="ERROR", status_message=msg)
                    _jobs[job_id].update({"state": "failed", "errorMsg": msg})
                    return

                data = resp.json()
                if data.get("errorCode") != 0:
                    msg = data.get("errorMsg", "unknown error")
                    span.update(level="ERROR", status_message=msg)
                    _jobs[job_id].update({"state": "failed", "errorMsg": msg})
                    return

                result = data["result"]
                pages = len(result.get("layoutParsingResults", []))
                span.update(output={"pages": pages})
                _lf.set_current_trace_io(output={"job_id": job_id, "pages": pages})
                _jobs[job_id].update({"state": "done", "result": result})

            except Exception as exc:
                msg = str(exc)
                span.update(level="ERROR", status_message=msg)
                _jobs[job_id].update({"state": "failed", "errorMsg": msg})


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
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, detail="empty file")

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"state": "processing", "created_at": time.monotonic()}
    asyncio.create_task(_run_ocr_job(job_id, file_bytes))
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
