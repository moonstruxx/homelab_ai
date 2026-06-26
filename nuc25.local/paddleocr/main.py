import base64
import io
import os
import httpx
import pypdfium2
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
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
        timeout=httpx.Timeout(60.0),
    ),
)

OCR_PROMPT = (
    "Extract all text from this image exactly as it appears. "
    "Return only the extracted text, preserving layout where possible."
)


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


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    data = await file.read()
    if not data:
        raise HTTPException(400, detail="empty file")

    mime = file.content_type or "image/png"
    b64  = base64.b64encode(data).decode()

    try:
        response = await client.chat.completions.create(
            model=VLLM_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": OCR_PROMPT},
                    ],
                }
            ],
            max_tokens=1024,
            temperature=0,
        )
        text = response.choices[0].message.content or ""
    except Exception as exc:
        raise HTTPException(502, detail=str(exc))

    return {"text": text, "model": VLLM_MODEL, "filename": file.filename}


@app.post("/api/v2/ocr/jobs")
async def ocr_jobs(request: Request):
    """RAGFlow v0.26+ PDF OCR endpoint. Accepts base64-encoded PDF, returns per-page text."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, detail="invalid JSON body")

    file_b64 = body.get("file")
    if not file_b64:
        raise HTTPException(400, detail="missing 'file' field")

    try:
        pdf_bytes = base64.b64decode(file_b64)
    except Exception:
        raise HTTPException(400, detail="invalid base64 in 'file' field")

    try:
        pdf = pypdfium2.PdfDocument(pdf_bytes)
    except Exception as exc:
        raise HTTPException(422, detail=f"failed to open PDF: {exc}")

    page_images = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=1.5)  # ~108 DPI
            page_images.append(bitmap.to_pil())
    finally:
        pdf.close()

    if not page_images:
        raise HTTPException(422, detail="PDF has no pages")

    layout_parsing_results = []
    for img in page_images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64_img = base64.b64encode(buf.getvalue()).decode()

        try:
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
            text = response.choices[0].message.content or ""
        except Exception as exc:
            raise HTTPException(502, detail=f"VLM backend error: {exc}")

        layout_parsing_results.append({
            "prunedResult": {
                "parsing_res_list": [
                    {
                        "block_content": text.strip(),
                        "block_label": "text",
                        "block_bbox": [0, 0, img.width, img.height],
                    }
                ]
            }
        })

    return {
        "errorCode": 0,
        "result": {
            "layoutParsingResults": layout_parsing_results,
        },
    }
