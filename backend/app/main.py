from __future__ import annotations

import hashlib
import hmac
import base64
import json
import logging
import math
import os
import queue
import re
import secrets
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request as UrlRequest, urlopen

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
from .local_agent import (
    AGENT_BUSY_MESSAGE,
    AgentCancelledError,
    AgentConfig,
    AgentError,
    release_agent_request,
    run_eurostat_agent,
    try_admit_agent_request,
)
from .title_agent import DEFAULT_TITLE_MODEL, TitleAgentError, generate_chat_title


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(os.getenv("EUROSTAT_STATIC_DIR", ROOT.parent / "frontend" / "static"))
ALLOW_UNLOCKED_VARIABLE = "APP_ALLOW_UNLOCKED"
logger = logging.getLogger(__name__)


def _app_password() -> str:
    return os.getenv("APP_PASSWORD", "")


def _require_app_lock_configuration() -> None:
    """Refuse to serve an unlocked app unless the operator explicitly opts in."""
    if _app_password():
        return
    if os.getenv(ALLOW_UNLOCKED_VARIABLE, "").strip().lower() in {"1", "true", "yes"}:
        logger.warning("APP_PASSWORD is not set; the app is running without its lock.")
        return
    raise RuntimeError(
        "APP_PASSWORD is not set. Set it to enable the app lock, or set "
        f"{ALLOW_UNLOCKED_VARIABLE}=true to run unlocked in a trusted environment."
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    _require_app_lock_configuration()
    yield


app = FastAPI(title="Eurostat Assistant", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

SESSION_COOKIE = "eurostat_lens_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
UNLOCK_WINDOW_SECONDS = 15 * 60
MAX_UNLOCK_FAILURES_PER_CLIENT = 5
MAX_UNLOCK_FAILURES_GLOBAL = 50
APP_VERSION = "0.3.0"
MODEL_ID_PATTERN = re.compile(r"^~?[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
FEEDBACK_CATEGORIES = (
    "Bug report",
    "Feature request",
    "Response quality",
    "General feedback",
)
MAX_FEEDBACK_CHARACTERS = 5_000
MAX_CHAT_LOG_BYTES = 1_000_000
AIRTABLE_ATTACHMENT_FIELD = "Chat log attachment"
AIRTABLE_ENVIRONMENT_VARIABLES = (
    "AIRTABLE_ACCESS_TOKEN",
    "AIRTABLE_BASE_ID",
    "AIRTABLE_TABLE_ID",
)


def _airtable_values() -> tuple[str, str, str]:
    return tuple(os.getenv(name, "").strip() for name in AIRTABLE_ENVIRONMENT_VARIABLES)


def _feedback_is_configured() -> bool:
    return all(_airtable_values())


# Sessions live in this process only, so locking can revoke them; a restart signs everyone out.
_sessions: dict[str, tuple[int, str]] = {}
_sessions_lock = threading.Lock()


def _password_fingerprint(password: str) -> str:
    return hashlib.sha256(f"eurostat-lens:{password}".encode("utf-8")).hexdigest()


def _session_token(password: str, expires_at: int) -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with _sessions_lock:
        for expired in [key for key, (expiry, _) in _sessions.items() if expiry <= now]:
            del _sessions[expired]
        _sessions[token] = (expires_at, _password_fingerprint(password))
    return token


def _valid_session_token(token: str | None, password: str, now: int | None = None) -> bool:
    if not token or not password:
        return False
    with _sessions_lock:
        session = _sessions.get(token)
    if session is None:
        return False
    expires_at, fingerprint = session
    if expires_at <= (int(time.time()) if now is None else now):
        return False
    # Changing APP_PASSWORD invalidates sessions issued under the old one.
    return hmac.compare_digest(fingerprint, _password_fingerprint(password))


def _revoke_session_token(token: str | None) -> None:
    if token:
        with _sessions_lock:
            _sessions.pop(token, None)


def _request_is_unlocked(request: Request) -> bool:
    password = _app_password()
    return not password or _valid_session_token(request.cookies.get(SESSION_COOKIE), password)


class UnlockThrottle:
    """Sliding-window limit on failed unlock attempts, per client and across all clients."""

    def __init__(self) -> None:
        self.clock = time.monotonic
        self._lock = threading.Lock()
        self._clients: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()

    def reset(self) -> None:
        with self._lock:
            self._clients.clear()
            self._global.clear()

    def _prune(self, now: float) -> None:
        cutoff = now - UNLOCK_WINDOW_SECONDS
        while self._global and self._global[0] <= cutoff:
            self._global.popleft()
        for client, attempts in list(self._clients.items()):
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if not attempts:
                del self._clients[client]

    def acquire(self, client: str) -> tuple[float, int | None]:
        """Reserve an attempt, counted as a failure until release() is called.

        Returns the reservation time and, when limited, the Retry-After seconds. Reserving
        before the password check stops concurrent requests from exceeding the limits.
        """
        with self._lock:
            now = self.clock()
            # Expired entries are dropped on every attempt and the global cap stops new
            # ones, so the per-client map never holds more clients than the global cap.
            self._prune(now)
            attempts = self._clients.get(client, deque())
            full = [
                window[0]
                for window, limit in (
                    (attempts, MAX_UNLOCK_FAILURES_PER_CLIENT),
                    (self._global, MAX_UNLOCK_FAILURES_GLOBAL),
                )
                if len(window) >= limit
            ]
            if full:
                retry_after = max(full) + UNLOCK_WINDOW_SECONDS - now
                return now, max(1, math.ceil(retry_after))
            attempts.append(now)
            self._clients[client] = attempts
            self._global.append(now)
            return now, None

    def release(self, client: str, reserved_at: float) -> None:
        """Clear the client's failures after a successful unlock."""
        with self._lock:
            self._clients.pop(client, None)
            try:
                self._global.remove(reserved_at)
            except ValueError:
                pass


unlock_throttle = UnlockThrottle()


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


def _title_model_name() -> str:
    selected = os.getenv("OPENROUTER_TITLE_MODEL", DEFAULT_TITLE_MODEL).strip()
    if not selected or not MODEL_ID_PATTERN.fullmatch(selected):
        raise RuntimeError("OPENROUTER_TITLE_MODEL contains an invalid model ID.")
    return selected


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


class ChatTitleRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ChatTitleResponse(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    model: str


class UnlockRequest(BaseModel):
    password: str = Field(min_length=1, max_length=512)


def _chat_log_bytes(chat_log: dict[str, Any]) -> bytes:
    return (
        json.dumps(chat_log, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
        + b"\n"
    )


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "Bug report",
        "Feature request",
        "Response quality",
        "General feedback",
    ]
    feedback: str = Field(min_length=1, max_length=MAX_FEEDBACK_CHARACTERS)
    rating: int = Field(ge=1, le=5)
    email: str | None = Field(default=None, max_length=254)
    chat_log: dict[str, Any] | None = None

    @field_validator("feedback")
    @classmethod
    def feedback_must_contain_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Feedback must contain text.")
        return cleaned

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not EMAIL_PATTERN.fullmatch(cleaned):
            raise ValueError("Enter a valid email address.")
        return cleaned

    @field_validator("chat_log")
    @classmethod
    def validate_chat_log(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if not (
            type(value.get("schemaVersion")) is int
            and isinstance(value.get("app"), dict)
            and isinstance(value.get("exportedAt"), str)
            and isinstance(value.get("investigation"), dict)
        ):
            raise ValueError("Chat log does not match the downloadable log schema.")
        try:
            encoded = _chat_log_bytes(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Chat log must be valid JSON.") from exc
        if len(encoded) > MAX_CHAT_LOG_BYTES:
            raise ValueError("Chat log is too large.")
        return value


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
    confidence: Literal["low", "medium", "high"] = "medium"
    model: str | None = None
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
        "feedback_configured": _feedback_is_configured(),
    }


@app.post("/api/auth/unlock")
def unlock(request: Request, credentials: UnlockRequest) -> JSONResponse:
    password = _app_password()
    if not password:
        return JSONResponse(
            {
                "authenticated": True,
                "lock_enabled": False,
                "feedback_configured": _feedback_is_configured(),
            }
        )
    client = request.client.host if request.client else "unknown"
    reserved_at, retry_after = unlock_throttle.acquire(client)
    if retry_after is not None:
        minutes = math.ceil(retry_after / 60)
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Too many unlock attempts. "
                f"Try again in {minutes} minute{'' if minutes == 1 else 's'}."
            },
            headers={"Cache-Control": "no-store", "Retry-After": str(retry_after)},
        )
    if not hmac.compare_digest(credentials.password.encode("utf-8"), password.encode("utf-8")):
        return JSONResponse(
            status_code=401,
            content={"detail": "Incorrect password."},
            headers={"Cache-Control": "no-store"},
        )

    unlock_throttle.release(client, reserved_at)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    response = JSONResponse(
        {
            "authenticated": True,
            "lock_enabled": True,
            "feedback_configured": _feedback_is_configured(),
        }
    )
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
def lock(request: Request) -> JSONResponse:
    _revoke_session_token(request.cookies.get(SESSION_COOKIE))
    response = JSONResponse(
        {
            "authenticated": False,
            "lock_enabled": bool(_app_password()),
            "feedback_configured": _feedback_is_configured(),
        }
    )
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {
        "ok": True,
        "agent_ready": bool(os.getenv("OPENROUTER_API_KEY")),
    }


class FeedbackConfigurationError(RuntimeError):
    pass


class FeedbackServiceError(RuntimeError):
    pass


def _airtable_configuration() -> tuple[str, str, str]:
    values = _airtable_values()
    if not all(values):
        raise FeedbackConfigurationError("Feedback storage is not configured.")
    return values


def _post_airtable_json(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = UrlRequest(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            response_body = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise FeedbackServiceError("Airtable did not accept the feedback.") from exc

    try:
        result = json.loads(response_body)
    except (TypeError, ValueError) as exc:
        raise FeedbackServiceError("Airtable returned an invalid response.") from exc
    if not isinstance(result, dict):
        raise FeedbackServiceError("Airtable returned an invalid response.")
    return result


def _create_feedback_record(feedback: FeedbackRequest) -> bool | None:
    token, base_id, table_id = _airtable_configuration()
    record_url = (
        f"https://api.airtable.com/v0/{quote(base_id, safe='')}/{quote(table_id, safe='')}"
    )
    fields: dict[str, Any] = {
        "Category": feedback.category,
        "Feedback": feedback.feedback,
        "Rating": feedback.rating,
    }
    if feedback.email:
        fields["email"] = feedback.email

    record = _post_airtable_json(
        record_url,
        token,
        {"fields": fields},
    )
    record_id = record.get("id")
    if not isinstance(record_id, str) or not record_id:
        raise FeedbackServiceError("Airtable did not return a record ID.")

    if feedback.chat_log is None:
        return None

    log_bytes = _chat_log_bytes(feedback.chat_log)
    attachment_url = (
        "https://content.airtable.com/v0/"
        f"{quote(base_id, safe='')}/{quote(record_id, safe='')}/"
        f"{quote(AIRTABLE_ATTACHMENT_FIELD, safe='')}/uploadAttachment"
    )
    try:
        _post_airtable_json(
            attachment_url,
            token,
            {
                "contentType": "application/json",
                "file": base64.b64encode(log_bytes).decode("ascii"),
                "filename": "eurostat-assistant-chat-log.json",
            },
        )
    except FeedbackServiceError:
        logger.warning("Feedback was saved, but its chat log attachment could not be uploaded.")
        return False
    return True


@app.post("/api/feedback")
async def submit_feedback(feedback: FeedbackRequest) -> dict[str, bool]:
    try:
        chat_log_attached = await anyio.to_thread.run_sync(_create_feedback_record, feedback)
    except FeedbackConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FeedbackServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail="Feedback could not be saved. Try again.",
        ) from exc
    response = {"ok": True}
    if chat_log_attached is not None:
        response["chat_log_attached"] = chat_log_attached
    return response


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
            "title_model": _title_model_name(),
            "data_source": "Eurostat public APIs",
            "history": "This browser (IndexedDB)",
        },
    }


def _agent_config(model: str | None = None) -> AgentConfig:
    return AgentConfig(
        model=_resolve_request_model(model),
        runner_path=ROOT / "app" / "sandbox_agent.py",
    )


def _admit_agent_request() -> None:
    """Reject the request before any work starts when running and waiting places are full."""
    if not try_admit_agent_request():
        raise HTTPException(status_code=429, detail=AGENT_BUSY_MESSAGE)


class _AgentStreamResponse(StreamingResponse):
    """Cancels the agent when the response ends for any reason, including a client disconnect."""

    def __init__(self, content: Any, cancel_event: threading.Event, **kwargs: Any) -> None:
        super().__init__(content, **kwargs)
        self.cancel_event = cancel_event

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.cancel_event.set()


def _public_response(result: Any, model: str | None = None) -> ChatResponse:
    return ChatResponse(
        answer=result.answer,
        confidence=result.confidence,
        model=model,
        result=result.result,
        tool_calls=result.tool_calls,
        tool_call_details=result.tool_call_details,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    agent_config = _agent_config(request.model)
    _admit_agent_request()
    try:
        result = await anyio.to_thread.run_sync(
            run_eurostat_agent,
            request.message,
            [message.model_dump() for message in request.history],
            request.summary,
            agent_config,
            request.context_result.model_dump(mode="json") if request.context_result else None,
        )
    except AgentError as exc:
        logger.error("Agent request failed: %s", exc)
        raise HTTPException(status_code=502, detail=exc.public_message) from exc
    finally:
        release_agent_request()

    return _public_response(result, agent_config.model)


@app.post("/api/chat/title", response_model=ChatTitleResponse)
async def chat_title(request: ChatTitleRequest) -> ChatTitleResponse:
    model = _title_model_name()
    try:
        title = await anyio.to_thread.run_sync(generate_chat_title, request.message, model)
    except TitleAgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ChatTitleResponse(title=title, model=model)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    agent_config = _agent_config(request.model)
    _admit_agent_request()
    event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
    cancel_event = threading.Event()

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
                cancel_event=cancel_event,
            )
            publish(
                {
                    "type": "result",
                    "data": _public_response(result, agent_config.model).model_dump(mode="json"),
                }
            )
        except AgentCancelledError:
            logger.info("Agent request cancelled after the client disconnected.")
        except AgentError as exc:
            logger.error("Agent request failed: %s", exc)
            publish({"type": "error", "message": exc.public_message})
        except Exception:
            logger.exception("Agent request failed unexpectedly.")
            publish({"type": "error", "message": "The agent request failed unexpectedly."})
        finally:
            release_agent_request()
            event_queue.put(None)

    async def events():
        yield json.dumps({"type": "status", "phase": "started"}) + "\n"
        while True:
            # Abandon the wait on disconnect so the response can cancel the agent at once.
            event = await anyio.to_thread.run_sync(event_queue.get, abandon_on_cancel=True)
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"

    # The thread owns the admitted place from here and releases it when the agent stops.
    try:
        threading.Thread(target=run_agent, daemon=True).start()
    except BaseException:
        release_agent_request()
        raise
    return _AgentStreamResponse(
        events(),
        cancel_event,
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
