from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path
from typing import Any, Literal

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .e2b_agent import AgentConfig, AgentError, run_eurostat_agent


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"

app = FastAPI(title="Eurostat Lens")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _model_name() -> str:
    model = os.getenv("OPENROUTER_MODEL") or os.getenv("OPENAI_MODEL") or "openai/gpt-4.1-mini"
    if "/" not in model:
        return f"openai/{model}"
    return model


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
    type: Literal["none", "line", "bar", "scatter"]
    orientation: Literal["horizontal", "vertical"] | None = None
    x: str | None = None
    y: str | None = None
    x_label: str | None = None
    y_label: str | None = None
    series: str | None = None
    label: str | None = None
    title: str | None = None


class DataResult(BaseModel):
    dataset: DatasetInfo
    sources: list[DatasetInfo] = Field(default_factory=list)
    filters: dict[str, list[str]]
    columns: list[ColumnInfo]
    rows: list[dict[str, Any]] = Field(max_length=500)
    chart: ChartIntent
    warnings: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=6)
    summary: str = Field(default="", max_length=2400)
    context_result: DataResult | None = None


class ToolCallDetail(BaseModel):
    id: str
    index: int = Field(ge=1)
    name: str
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


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {
        "ok": True,
        "agent_ready": bool(os.getenv("E2B_API_KEY") and os.getenv("OPENROUTER_API_KEY")),
    }


def _agent_config() -> AgentConfig:
    return AgentConfig(
        model=_model_name(),
        skill_path=ROOT / "SKILL.md",
        helper_path=ROOT / "scripts" / "eurostat_api.py",
        sandbox_agent_path=ROOT / "app" / "sandbox_agent.py",
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
            _agent_config(),
            request.context_result.model_dump(mode="json") if request.context_result else None,
        )
    except AgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _public_response(result)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    event_queue: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def publish(event: dict[str, Any]) -> None:
        event_queue.put(event)

    def run_agent() -> None:
        try:
            result = run_eurostat_agent(
                request.message,
                [message.model_dump() for message in request.history],
                request.summary,
                _agent_config(),
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
