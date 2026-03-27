import os
import json
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-reasoner")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LEGAL_SERVER_URL = os.environ.get("LEGAL_SERVER_URL", "https://legal-server-production.up.railway.app/legal/run")
LEGAL_MODEL_NAME = "legal-nda"


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {"id": DEEPSEEK_MODEL, "object": "model", "owned_by": "deepseek"},
            {"id": LEGAL_MODEL_NAME, "object": "model", "owned_by": "wuyun-legal"},
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "")

    if model == LEGAL_MODEL_NAME:
        return await _route_legal(body)
    else:
        return await _route_deepseek(body)


async def _route_legal(body: dict):
    messages = body.get("messages", [])
    # 取最後一條 user 訊息作為 NDA 文字
    text = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            text = m.get("content", "")
            break

    payload = {"cmd": "triage-nda", "text": text, "locale": "zh-TW"}

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(LEGAL_SERVER_URL, json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            return JSONResponse(status_code=502, content={"error": str(e)})

    data = resp.json()

    # 把 legal 結果轉成可讀文字
    risk = data.get("risk_level", "unknown").upper()
    summary = data.get("summary", "")
    issues = data.get("issues", [])
    recommendation = data.get("recommendation", "")
    marker = data.get("marker", "")

    lines = [f"## NDA 風險評估結果\n", f"**風險等級：{risk}**\n", f"{summary}\n"]
    if issues:
        lines.append("\n### 問題條款\n")
        for i in issues:
            severity = i.get("severity", "").upper()
            clause = i.get("clause", "")
            desc = i.get("description", "")
            lines.append(f"- **[{severity}] {clause}**：{desc}")
    if recommendation:
        lines.append(f"\n### 建議\n{recommendation}")
    if marker:
        lines.append(f"\n\n---\n{marker}")

    content = "\n".join(lines)

    return {
        "id": "legal-0001",
        "object": "chat.completion",
        "model": LEGAL_MODEL_NAME,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def _route_deepseek(body: dict):
    is_reasoner = "reasoner" in body.get("model", DEEPSEEK_MODEL)
    if is_reasoner:
        body.pop("temperature", None)
        body.setdefault("max_tokens", 8000)
    else:
        body.setdefault("max_tokens", 1024)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            resp = await client.post(DEEPSEEK_BASE, headers=headers, json=body)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            return JSONResponse(status_code=502, content={"error": str(e)})

    return resp.json()
