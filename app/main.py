from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Any, Literal

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent_config import (
    MAX_ESTIMATED_CELLS,
    MAX_EUROSTAT_RESPONSE_BYTES,
    MAX_RECENT_MESSAGES,
    MAX_RESULT_ROWS,
    MAX_SUMMARY_CHARACTERS,
    MAX_TIME_PERIODS,
    MAX_TOOL_CALLS,
    TOOL_CALL_LIMITS,
    TOOLS,
)
from .local_agent import AgentConfig, AgentError, run_eurostat_agent


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"

app = FastAPI(title="Eurostat Assistant")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SESSION_COOKIE = "eurostat_lens_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
APP_VERSION = "0.3.0"
MODEL_ID_PATTERN = re.compile(r"^~?[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


def _app_password() -> str:
    return os.getenv("APP_PASSWORD", "")


def _session_token(password: str, expires_at: int) -> str:
    payload = str(expires_at)
    signature = hmac.new(
        password.encode("utf-8"),
        f"eurostat-lens:{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


def _valid_session_token(token: str | None, password: str, now: int | None = None) -> bool:
    if not token or not password:
        return False
    try:
        expires_text, _ = token.split(".", 1)
        expires_at = int(expires_text)
    except (TypeError, ValueError):
        return False
    if expires_at <= (int(time.time()) if now is None else now):
        return False
    expected = _session_token(password, expires_at)
    return hmac.compare_digest(token, expected)


def _request_is_unlocked(request: Request) -> bool:
    password = _app_password()
    return not password or _valid_session_token(request.cookies.get(SESSION_COOKIE), password)


@app.middleware("http")
async def require_app_unlock(request: Request, call_next):
    path = request.url.path
    is_public = (
        not path.startswith("/api/")
        or path.startswith("/api/auth/")
        or path == "/api/health"
    )
    if is_public or _request_is_unlocked(request):
        return await call_next(request)
    return JSONResponse(
        status_code=401,
        content={"detail": "App is locked. Enter the app password to continue."},
        headers={"Cache-Control": "no-store"},
    )


def _model_name() -> str:
    return _available_models()[0]


def _available_models() -> list[str]:
    configured = os.getenv("OPENROUTER_MODEL_OPTIONS", "")
    candidates = [item.strip() for item in configured.split(",") if item.strip()]
    if not candidates:
        raise RuntimeError(
            "Missing OPENROUTER_MODEL_OPTIONS. Define the comma-separated model list in .env."
        )
    invalid = [model for model in candidates if not MODEL_ID_PATTERN.fullmatch(model)]
    if invalid:
        raise RuntimeError("OPENROUTER_MODEL_OPTIONS contains an invalid model ID.")
    return list(dict.fromkeys(candidates))


def _model_label(model: str) -> str:
    model_name = model.rsplit("/", 1)[-1]
    replacements = {"gpt": "GPT", "mini": "mini"}
    return " ".join(
        replacements.get(part.lower(), part.capitalize())
        for part in model_name.replace("_", "-").split("-")
    )


def _resolve_request_model(model: str | None) -> str:
    selected = model or _model_name()
    if selected not in _available_models():
        raise HTTPException(
            status_code=400,
            detail="The selected model is not enabled for this deployment.",
        )
    return selected


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class DatasetInfo(BaseModel):
    code: str
    title: str
    updated: str | None = None
    source_url: str


class ColumnInfo(BaseModel):
    key: str
    label: str


class ChartIntent(BaseModel):
    type: Literal[
        "none",
        "line",
        "area",
        "bar",
        "dot",
        "scatter",
        "heatmap",
        "histogram",
        "boxplot",
    ]
    purpose: Literal[
        "trend",
        "comparison",
        "relationship",
        "distribution",
        "composition",
        "change",
    ] | None = None
    orientation: Literal["horizontal", "vertical"] | None = None
    x: str | None = None
    y: str | None = None
    color: str | None = None
    size: str | None = None
    x_label: str | None = None
    y_label: str | None = None
    series: str | None = None
    label: str | None = None
    title: str | None = None
    stack: Literal["none", "stacked", "normalize"] = "none"
    sort: Literal["natural", "ascending", "descending"] = "natural"
    top_n: int | None = Field(default=None, ge=1, le=50)
    trendline: Literal["none", "linear"] = "none"
    labels: Literal["hover", "always"] = "hover"
    scale: Literal["linear", "log"] = "linear"
    zero_baseline: bool | Literal["auto"] = "auto"


class SourceTable(BaseModel):
    dataset: DatasetInfo
    filters: dict[str, list[str]]
    columns: list[ColumnInfo]
    rows: list[dict[str, Any]] = Field(max_length=500)
    warnings: list[str] = Field(default_factory=list)


class DataResult(BaseModel):
    dataset: DatasetInfo
    sources: list[DatasetInfo] = Field(default_factory=list)
    source_tables: list[SourceTable] = Field(default_factory=list)
    filters: dict[str, list[str]]
    columns: list[ColumnInfo]
    rows: list[dict[str, Any]] = Field(max_length=500)
    chart: ChartIntent
    warnings: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=MAX_RECENT_MESSAGES)
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARACTERS)
    context_result: DataResult | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)


class UnlockRequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class ToolCallDetail(BaseModel):
    id: str
    index: int = Field(ge=1)
    name: str
    reason: str = Field(default="", max_length=180)
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: Literal["running", "completed", "error"]
    duration_ms: int | None = Field(default=None, ge=0)
    result_preview: str = Field(default="", max_length=700)


class ChatResponse(BaseModel):
    answer: str
    result: DataResult | None = None
    tool_calls: int = Field(default=0, ge=0)
    tool_call_details: list[ToolCallDetail] = Field(default_factory=list)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/settings/development")
def development_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/auth/status")
def auth_status(request: Request) -> dict[str, bool]:
    lock_enabled = bool(_app_password())
    return {
        "lock_enabled": lock_enabled,
        "authenticated": not lock_enabled or _request_is_unlocked(request),
    }


@app.post("/api/auth/unlock")
def unlock(request: Request, credentials: UnlockRequest) -> JSONResponse:
    password = _app_password()
    if not password:
        return JSONResponse({"authenticated": True, "lock_enabled": False})
    if not hmac.compare_digest(credentials.password.encode("utf-8"), password.encode("utf-8")):
        return JSONResponse(
            status_code=401,
            content={"detail": "Incorrect password."},
            headers={"Cache-Control": "no-store"},
        )

    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    response = JSONResponse({"authenticated": True, "lock_enabled": True})
    response.set_cookie(
        key=SESSION_COOKIE,
        value=_session_token(password, expires_at),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/auth/lock")
def lock() -> JSONResponse:
    response = JSONResponse({"authenticated": False, "lock_enabled": bool(_app_password())})
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {
        "ok": True,
        "agent_ready": bool(os.getenv("OPENROUTER_API_KEY")),
    }


@app.get("/api/settings/development")
def development_settings() -> dict[str, Any]:
    default_model = _model_name()
    return {
        "app_version": APP_VERSION,
        "default_model": default_model,
        "models": [
            {
                "id": model,
                "label": _model_label(model),
                "description": (
                    "Fast, cost-aware default for focused data questions."
                    if model.endswith("mini")
                    else "Higher-capability option for more involved investigations."
                ),
            }
            for model in _available_models()
        ],
        "tools": [
            {
                "name": tool["function"]["name"],
                "description": tool["function"]["description"],
                "per_request_limit": TOOL_CALL_LIMITS[tool["function"]["name"]],
            }
            for tool in TOOLS
        ],
        "limits": {
            "tool_calls": MAX_TOOL_CALLS,
            "result_rows": MAX_RESULT_ROWS,
            "estimated_cells": MAX_ESTIMATED_CELLS,
            "eurostat_response_bytes": MAX_EUROSTAT_RESPONSE_BYTES,
            "time_periods": MAX_TIME_PERIODS,
            "recent_messages": MAX_RECENT_MESSAGES,
            "summary_characters": MAX_SUMMARY_CHARACTERS,
        },
        "runtime": {
            "model_gateway": "OpenRouter",
            "data_source": "Eurostat public APIs",
            "history": "This browser (IndexedDB)",
        },
    }


def _agent_config(model: str | None = None) -> AgentConfig:
    return AgentConfig(
        model=_resolve_request_model(model),
        runner_path=ROOT / "app" / "sandbox_agent.py",
    )


def _public_response(result: Any) -> ChatResponse:
    return ChatResponse(
        answer=result.answer,
        result=result.result,
        tool_calls=result.tool_calls,
        tool_call_details=result.tool_call_details,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    try:
        result = await anyio.to_thread.run_sync(
            run_eurostat_agent,
            request.message,
            [message.model_dump() for message in request.history],
            request.summary,
            _agent_config(request.model),
            request.context_result.model_dump(mode="json") if request.context_result else None,
        )
    except AgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _public_response(result)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    agent_config = _agent_config(request.model)
    event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def publish(event: dict[str, Any]) -> None:
        event_queue.put(event)

    def run_agent() -> None:
        try:
            result = run_eurostat_agent(
                request.message,
                [message.model_dump() for message in request.history],
                request.summary,
                agent_config,
                request.context_result.model_dump(mode="json") if request.context_result else None,
                on_event=publish,
            )
            publish({"type": "result", "data": _public_response(result).model_dump(mode="json")})
        except AgentError as exc:
            publish({"type": "error", "message": str(exc)})
        except Exception:
            publish({"type": "error", "message": "The agent request failed unexpectedly."})
        finally:
            event_queue.put(None)

    async def events():
        threading.Thread(target=run_agent, daemon=True).start()
        yield json.dumps({"type": "status", "phase": "started"}) + "\n"
        while True:
            event = await anyio.to_thread.run_sync(event_queue.get)
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
