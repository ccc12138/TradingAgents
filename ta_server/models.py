from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field


AnalystType = Literal["market", "social", "news", "fundamentals"]
AgentStatus = Literal["pending", "in_progress", "completed", "error"]
RunStatus = Literal["queued", "running", "completed", "error"]

def _default_analysis_date() -> str:
    d = datetime.now().date()
    # Weekend rollback (Sat/Sun -> Fri) to avoid invalid/future market dates.
    if d.weekday() == 5:  # Saturday
        d = d - timedelta(days=1)
    elif d.weekday() == 6:  # Sunday
        d = d - timedelta(days=2)
    return d.isoformat()


class RunCreateRequest(BaseModel):
    ticker: str = Field(..., min_length=1, description="Ticker symbol, e.g. NVDA")
    analysis_date: str = Field(default_factory=_default_analysis_date, description="YYYY-MM-DD")
    analysts: list[AnalystType] = Field(
        default_factory=lambda: ["market", "social", "news", "fundamentals"]
    )
    research_depth: int = Field(3, ge=1, le=5, description="Debate/discuss rounds")

    llm_provider: str = Field("openai", description="openai|openrouter|anthropic|google|ollama")
    backend_url: str = Field("https://api.openai.com/v1")
    quick_think_llm: str = Field("gpt-4o-mini")
    deep_think_llm: str = Field("o4-mini")

    language: str = Field("en", description="en|zh")

    # Optional overrides for data vendor routing (same shape as DEFAULT_CONFIG)
    data_vendors: dict[str, str] | None = None
    tool_vendors: dict[str, str] | None = None
    disable_vendor_fallback: bool | None = None


class RunCreateResponse(BaseModel):
    run_id: str


class RunSummary(BaseModel):
    run_id: str
    created_at: datetime
    status: RunStatus
    ticker: str
    analysis_date: str
    research_depth: int


class RunDetail(BaseModel):
    run_id: str
    created_at: datetime
    status: RunStatus
    ticker: str
    analysis_date: str
    research_depth: int
    analysts: list[AnalystType]
    agent_status: dict[str, AgentStatus]
    reports: dict[str, str]
    final_trade_decision: str | None = None
    error: str | None = None


class StreamEvent(BaseModel):
    type: str
    ts: datetime
    run_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
