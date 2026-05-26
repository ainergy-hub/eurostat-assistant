from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import anyio
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .e2b_agent import AgentConfig, AgentError, run_eurostat_agent


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"

app = FastAPI(title="Eurostat E2B Chat")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _model_name() -> str:
    model = os.getenv("OPENROUTER_MODEL") or os.getenv("OPENAI_MODEL") or "openai/gpt-4.1-mini"
    if "/" not in model:
        return f"openai/{model}"
    return model


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)


class ChatResponse(BaseModel):
    answer: str
    sandbox_stdout: str = ""


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {
        "ok": True,
        "has_e2b_api_key": bool(os.getenv("E2B_API_KEY")),
        "has_openrouter_api_key": bool(os.getenv("OPENROUTER_API_KEY")),
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    config = AgentConfig(
        model=_model_name(),
        skill_path=ROOT / "SKILL.md",
        helper_path=ROOT / "scripts" / "eurostat_api.py",
        sandbox_agent_path=ROOT / "app" / "sandbox_agent.py",
    )

    try:
        result = await anyio.to_thread.run_sync(
            run_eurostat_agent,
            request.message,
            [message.model_dump() for message in request.history],
            config,
        )
    except AgentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChatResponse(answer=result.answer, sandbox_stdout=result.stdout)
