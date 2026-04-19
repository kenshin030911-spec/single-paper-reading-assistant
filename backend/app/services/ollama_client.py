import json
import os
import re
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = "deepseek-r1:8b"
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "embeddinggemma")
CHECK_TIMEOUT_SECONDS = 10.0
CHAT_TIMEOUT_SECONDS = 600.0
EMBED_TIMEOUT_SECONDS = 120.0


class OllamaServiceError(RuntimeError):
    """Ollama 服务不可用、模型缺失或返回异常时抛出的统一异常。"""


def ensure_ollama_ready() -> None:
    """先检查 Ollama 服务可连，再确认 deepseek-r1:8b 可用。"""
    _ensure_model_ready(OLLAMA_MODEL)


def ensure_embedding_model_ready() -> None:
    """检查 embedding 模型可连可用。"""
    _ensure_model_ready(OLLAMA_EMBED_MODEL)


def generate_embeddings(inputs: list[str]) -> list[list[float]]:
    """使用 Ollama embeddings 接口生成向量。"""
    if not inputs:
        return []

    ensure_embedding_model_ready()
    payload = {
        "model": OLLAMA_EMBED_MODEL,
        "input": inputs,
    }
    response = _request("POST", "/api/embed", json=payload, timeout=EMBED_TIMEOUT_SECONDS)
    data = response.json()
    raw_embeddings = data.get("embeddings")

    if not isinstance(raw_embeddings, list):
        raise OllamaServiceError("Ollama embeddings 返回格式不符合预期。")

    embeddings: list[list[float]] = []
    for item in raw_embeddings:
        if not isinstance(item, list):
            raise OllamaServiceError("Ollama embeddings 返回了非向量数据。")

        try:
            vector = [float(value) for value in item]
        except (TypeError, ValueError) as exc:
            raise OllamaServiceError("Ollama embeddings 向量中包含无效值。") from exc

        embeddings.append(vector)

    return embeddings


def _ensure_model_ready(model_name: str) -> None:
    """先检查 Ollama 服务可连，再确认指定模型已存在。"""
    tags_response = _request("GET", "/api/tags", timeout=CHECK_TIMEOUT_SECONDS)
    models = tags_response.json().get("models", [])
    model_names = {item.get("name") for item in models if isinstance(item, dict)}
    canonical_model_names = {
        name.split(":", maxsplit=1)[0]
        for name in model_names
        if isinstance(name, str) and name
    }

    if model_name not in model_names and model_name not in canonical_model_names:
        raise OllamaServiceError(
            f"Ollama 已启动，但未发现模型 {model_name}。"
            f"请先执行 `ollama pull {model_name}`。"
        )

    _request(
        "POST",
        "/api/show",
        json={"model": model_name},
        timeout=CHECK_TIMEOUT_SECONDS,
    )


def generate_structured_output(
    system_prompt: str,
    user_prompt: str,
    response_model: type[BaseModel],
) -> BaseModel:
    """使用 Ollama structured outputs 生成可校验的 JSON。"""
    ensure_ollama_ready()
    schema = response_model.model_json_schema()
    schema_text = json.dumps(schema, ensure_ascii=False)

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": schema,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"{user_prompt}\n\n"
                    f"请严格遵循以下 JSON Schema 返回，不要输出额外解释：\n{schema_text}"
                ),
            },
        ],
    }
    response = _request("POST", "/api/chat", json=payload, timeout=CHAT_TIMEOUT_SECONDS)
    content = _extract_message_content(response.json())
    cleaned_content = _clean_json_text(content)

    try:
        return response_model.model_validate_json(cleaned_content)
    except ValidationError as exc:
        raise OllamaServiceError("Ollama 返回了结果，但结构化 JSON 解析失败。") from exc


def generate_text_response(
    system_prompt: str,
    user_prompt: str,
    chat_history: list[dict[str, str]] | None = None,
) -> str:
    """普通问答走文本输出，并尽量清理深度思考标签。"""
    ensure_ollama_ready()
    messages = [{"role": "system", "content": system_prompt}]

    if chat_history:
        messages.extend(chat_history)

    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "options": {"temperature": 0.2},
        "messages": messages,
    }
    response = _request("POST", "/api/chat", json=payload, timeout=CHAT_TIMEOUT_SECONDS)
    content = _extract_message_content(response.json())
    cleaned_content = _clean_text_response(content)

    if not cleaned_content:
        raise OllamaServiceError("Ollama 没有返回有效回答。")

    return cleaned_content


def _request(
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    timeout: float,
) -> httpx.Response:
    """统一处理 Ollama HTTP 请求和错误信息。"""
    try:
        with httpx.Client(base_url=OLLAMA_BASE_URL, timeout=timeout) as client:
            response = client.request(method, path, json=json)
    except httpx.RequestError as exc:
        raise OllamaServiceError(
            f"无法连接到 Ollama 服务（{OLLAMA_BASE_URL}）。请先启动 Ollama。"
        ) from exc

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        raise OllamaServiceError(f"Ollama 请求失败：{detail}")

    return response


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or f"HTTP {response.status_code}"

    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("detail") or response.status_code)

    return str(payload)


def _extract_message_content(payload: dict[str, Any]) -> str:
    message = payload.get("message", {})
    content = message.get("content", "")

    if not isinstance(content, str):
        raise OllamaServiceError("Ollama 返回格式不符合预期，缺少 message.content。")

    return content.strip()


def _clean_text_response(text: str) -> str:
    # deepseek-r1 有时会包含思考过程标签，这里先去掉再返回给前端。
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return cleaned or text.strip()


def _clean_json_text(text: str) -> str:
    cleaned = _clean_text_response(text)

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    return cleaned
