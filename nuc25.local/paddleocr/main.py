import base64
import os
import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File
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
