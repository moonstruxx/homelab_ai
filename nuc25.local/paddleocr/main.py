import asyncio
import base64
import io
import os

import httpx
import pypdfium2
from fastapi import FastAPI, HTTPException, Request
from openai import AsyncOpenAI

app = FastAPI(title="PaddleOCR VLM Proxy")

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


async def _ocr_page(b64_img: str) -> str:
    response = await client.chat.completions.create(
        model=VLLM_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}},
                {"type": "text", "text": OCR_PROMPT},
            ],
        }],
        max_tokens=2048,
        temperature=0,
    )
    return response.choices[0].message.content or ""


@app.post("/")
async def ocr_sync(request: Request):
    """RAGFlow PaddleOCR synchronous API: JSON body → layoutParsingResults."""
    body = await request.json()
    file_b64 = body.get("file", "")
    file_type = int(body.get("fileType", 0))

    try:
        data = base64.b64decode(file_b64)
    except Exception:
        raise HTTPException(400, "invalid base64 file")

    if file_type == 0:  # PDF
        pdf = pypdfium2.PdfDocument(data)
        try:
            page_b64s = []
            for i in range(len(pdf)):
                bitmap = pdf[i].render(scale=1.5)
                buf = io.BytesIO()
                bitmap.to_pil().save(buf, format="PNG")
                page_b64s.append(base64.b64encode(buf.getvalue()).decode())
        finally:
            pdf.close()
        texts = await asyncio.gather(*[_ocr_page(b64) for b64 in page_b64s])
    else:  # image
        texts = [await _ocr_page(file_b64)]

    layout_parsing_results = [
        {"prunedResult": {"parsing_res_list": [{"block_content": t.strip(), "block_label": "text", "block_bbox": [0, 0, 0, 0]}]}}
        for t in texts
    ]
    return {"errorCode": 0, "result": {"layoutParsingResults": layout_parsing_results}}
