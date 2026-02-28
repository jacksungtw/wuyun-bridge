# -*- coding: utf-8 -*-
"""
flask_bridge_final.py  (Wuyun Bridge v7.1)
"""

import os
import json
import traceback
from typing import Tuple, Optional

import requests
from flask import Flask, request, jsonify, Response

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()

JETSON_CHAT_URL = os.getenv(
    "JETSON_CHAT_URL",
    "http://192.168.213.72:8080/v1/chat/completions",
).strip()

ANYTHINGLLM_URL = os.getenv(
    "ANYTHINGLLM_URL",
    "http://127.0.0.1:3001/api/v1/openai/chat/completions",
).strip()
ANYTHINGLLM_API_KEY = os.getenv("ANYTHINGLLM_API_KEY", "").strip()
ANYTHINGLLM_MODEL = os.getenv("ANYTHINGLLM_MODEL", "jack").strip()

MAX_BODY_BYTES = int(os.getenv("BRIDGE_MAX_BODY_BYTES", "5242880"))

app = Flask(__name__)


def _limit_request_size() -> Tuple[bool, Optional[Response]]:
    length = request.content_length or 0
    if length > MAX_BODY_BYTES:
        return (
            False,
            jsonify({"error": {"message": f"Request body too large: {length} bytes (limit {MAX_BODY_BYTES})", "type": "request_too_large"}}),
        )
    return True, None


def _safe_get_json() -> dict:
    try:
        obj = request.get_json(silent=True)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _proxy_openai_like(url: str, payload: dict, headers_extra: dict = None, timeout=(10, 300)):
    headers = {"Content-Type": "application/json"}
    if headers_extra:
        headers.update(headers_extra)
    resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    return Response(
        resp.content,
        status=resp.status_code,
        content_type=resp.headers.get("Content-Type", "application/json"),
    )


def call_openai(payload: dict):
    if not OPENAI_API_KEY:
        return jsonify({"error": {"message": "OPENAI_API_KEY 未設定。", "type": "config_error"}}), 500
    url = f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions"
    payload = dict(payload)
    print(f"[Bridge] → OpenAI {payload.get('model','(no model)')}")
    return _proxy_openai_like(url, payload, headers_extra={"Authorization": f"Bearer {OPENAI_API_KEY}"}, timeout=(10, 300))


def call_jetson(payload: dict):
    url = JETSON_CHAT_URL
    payload = dict(payload)
    print(f"[Bridge] → Jetson1 LLM @ {url}")
    try:
        return _proxy_openai_like(url, payload, timeout=(5, 240))
    except requests.exceptions.Timeout:
        print("[Bridge] Jetson1 超時，改用 OpenAI 後援")
        fallback = dict(payload)
        fallback["model"] = "gpt-4o"
        return call_openai(fallback)
    except requests.exceptions.RequestException as e:
        print(f"[Bridge] Jetson1 呼叫失敗：{e}，改用 OpenAI 後援")
        fallback = dict(payload)
        fallback["model"] = "gpt-4o"
        return call_openai(fallback)


def call_anythingllm(payload: dict):
    if not ANYTHINGLLM_API_KEY:
        return jsonify({"error": {"message": "ANYTHINGLLM_API_KEY 未設定。", "type": "config_error"}}), 500
    url = ANYTHINGLLM_URL
    payload = dict(payload)
    payload["model"] = ANYTHINGLLM_MODEL
    headers = {
        "Authorization": f"Bearer {ANYTHINGLLM_API_KEY}",
        "x-api-key": ANYTHINGLLM_API_KEY,
    }
    print(f"[Bridge] → AnythingLLM {ANYTHINGLLM_MODEL} @ {url}")
    return _proxy_openai_like(url, payload, headers_extra=headers, timeout=(10, 300))


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "bridge": "wuyun-bridge-v7.1",
        "openai_key_set": bool(OPENAI_API_KEY),
        "jetson_url": JETSON_CHAT_URL,
        "anythingllm_url": ANYTHINGLLM_URL,
        "anythingllm_model": ANYTHINGLLM_MODEL,
        "anythingllm_key_set": bool(ANYTHINGLLM_API_KEY),
    })


@app.route("/v1/models", methods=["GET"])
@app.route("/models", methods=["GET"])
def list_models():
    data = [
        {"id": "gpt-4o", "object": "model"},
        {"id": "deepseek", "object": "model"},
        {"id": "wuyun-rag", "object": "model"},
    ]
    return jsonify({"object": "list", "data": data})


@app.route("/v1/chat/completions", methods=["POST"])
@app.route("/chat/completions", methods=["POST"])
def chat_completions():
    ok, resp = _limit_request_size()
    if not ok:
        return resp

    if not request.content_type or "application/json" not in request.content_type:
        return jsonify({"error": {"message": "Content-Type 必須是 application/json", "type": "invalid_request_error"}}), 400

    payload = _safe_get_json()
    if not isinstance(payload, dict):
        return jsonify({"error": {"message": "無法解析 JSON payload。", "type": "invalid_json"}}), 400

    model = str(payload.get("model", "gpt-4o")).strip() or "gpt-4o"
    print(f"[Bridge] 收到請求 model={model}")

    try:
        m = model.lower()
        if m in ["deepseek", "jetson", "jetson1-deepseek"]:
            return call_jetson(payload)
        if m in ["wuyun-rag", "anythingllm", "anythingllm-rag", "rag"]:
            return call_anythingllm(payload)
        return call_openai(payload)
    except Exception as e:
        print("[Bridge] 未預期錯誤：", e)
        traceback.print_exc()
        return jsonify({"error": {"message": f"Bridge exception: {e}", "type": "bridge_internal_error"}}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8012))
    app.run(host="0.0.0.0", port=port, debug=False)
