from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

from .models import AgentStatus, RunCreateRequest, RunDetail, RunStatus, RunSummary


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _extract_content_string(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "tool_use":
                    text_parts.append(f"[Tool: {item.get('name', 'unknown')}]")
            else:
                text_parts.append(str(item))
        return " ".join(text_parts)
    return str(content)


def _normalize_tool_call(tool_call: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(tool_call, dict):
        return str(tool_call.get("name", "unknown")), dict(tool_call.get("args", {}) or {})
    name = getattr(tool_call, "name", None)
    args = getattr(tool_call, "args", None)
    return str(name or "unknown"), dict(args or {})


_DEFAULT_AGENT_STATUS: dict[str, AgentStatus] = {
    "Market Analyst": "pending",
    "Social Analyst": "pending",
    "News Analyst": "pending",
    "Fundamentals Analyst": "pending",
    "Bull Researcher": "pending",
    "Bear Researcher": "pending",
    "Research Manager": "pending",
    "Trader": "pending",
    "Risky Analyst": "pending",
    "Safe Analyst": "pending",
    "Neutral Analyst": "pending",
    "Risk Judge": "pending",
}


@dataclass
class RunSession:
    run_id: str
    request: RunCreateRequest
    created_at: datetime = field(default_factory=_now)
    status: RunStatus = "queued"
    agent_status: dict[str, AgentStatus] = field(
        default_factory=lambda: dict(_DEFAULT_AGENT_STATUS)
    )
    reports: dict[str, str] = field(default_factory=dict)
    final_trade_decision: str | None = None
    error: str | None = None

    _events: list[dict[str, Any]] = field(default_factory=list)
    _events_max: int = 2000
    _subscribers: set[asyncio.Queue] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def snapshot(self) -> RunDetail:
        return RunDetail(
            run_id=self.run_id,
            created_at=self.created_at,
            status=self.status,
            ticker=self.request.ticker,
            analysis_date=self.request.analysis_date,
            research_depth=self.request.research_depth,
            analysts=self.request.analysts,
            agent_status=dict(self.agent_status),
            reports=dict(self.reports),
            final_trade_decision=self.final_trade_decision,
            error=self.error,
        )

    def list_events(self, *, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            if limit <= 0:
                return []
            return list(self._events[-limit:])

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def _append_event(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        if len(self._events) > self._events_max:
            drop = len(self._events) - self._events_max
            del self._events[:drop]

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        event = {
            "type": event_type,
            "ts": _now().isoformat(),
            "run_id": self.run_id,
            "payload": payload,
        }

        loop = self._loop
        with self._lock:
            self._append_event(event)
            subscribers = list(self._subscribers)

        if loop is None:
            return

        for queue in subscribers:
            loop.call_soon_threadsafe(_queue_put_nowait_drop_oldest, queue, event)

    def _set_agent_status(self, agent: str, status: AgentStatus) -> None:
        changed = False
        if agent not in self.agent_status:
            self.agent_status[agent] = status
            changed = True
        elif self.agent_status[agent] != status:
            self.agent_status[agent] = status
            changed = True

        if changed:
            self.emit("status_update", {"agent": agent, "status": status})

    def _set_report(self, section: str, content: str) -> None:
        content = content or ""
        if not content:
            return
        if self.reports.get(section) == content:
            return
        self.reports[section] = content
        self.emit("report_update", {"section": section, "content": content})

    def run(self) -> None:
        self.status = "running"
        self.emit("run_status", {"status": self.status})

        try:
            config = DEFAULT_CONFIG.copy()
            config["language"] = self.request.language
            config["max_debate_rounds"] = int(self.request.research_depth)
            config["max_risk_discuss_rounds"] = int(self.request.research_depth)
            config["quick_think_llm"] = self.request.quick_think_llm
            config["deep_think_llm"] = self.request.deep_think_llm
            config["backend_url"] = self.request.backend_url
            config["llm_provider"] = self.request.llm_provider.lower()

            if self.request.data_vendors is not None:
                config["data_vendors"] = dict(self.request.data_vendors)
            if self.request.tool_vendors is not None:
                config["tool_vendors"] = dict(self.request.tool_vendors)
            if self.request.disable_vendor_fallback is not None:
                config["disable_vendor_fallback"] = bool(self.request.disable_vendor_fallback)

            selected_analysts = list(self.request.analysts)
            if not selected_analysts:
                raise ValueError("No analysts selected.")

            self._set_agent_status(f"{selected_analysts[0].capitalize()} Analyst", "in_progress")

            graph = TradingAgentsGraph(selected_analysts=selected_analysts, config=config, debug=True)

            init_agent_state = graph.propagator.create_initial_state(
                self.request.ticker, self.request.analysis_date
            )
            args = graph.propagator.get_graph_args()

            last_seen: dict[str, str] = {}
            for chunk in graph.graph.stream(init_agent_state, **args):
                if chunk.get("messages"):
                    last_message = chunk["messages"][-1]
                    content = _extract_content_string(getattr(last_message, "content", str(last_message)))
                    self.emit("message", {"content": content})

                    tool_calls = getattr(last_message, "tool_calls", None)
                    if tool_calls:
                        for tc in tool_calls:
                            name, tc_args = _normalize_tool_call(tc)
                            self.emit("tool_call", {"name": name, "args": tc_args})

                # Reports: only emit on change
                for section in (
                    "market_report",
                    "sentiment_report",
                    "news_report",
                    "fundamentals_report",
                    "investment_plan",
                    "trader_investment_plan",
                    "final_trade_decision",
                ):
                    value = chunk.get(section)
                    if isinstance(value, str) and value and last_seen.get(section) != value:
                        last_seen[section] = value
                        self._set_report(section, value)

                # Status heuristics, similar to CLI
                if last_seen.get("market_report"):
                    self._set_agent_status("Market Analyst", "completed")
                    next_analyst = _next_selected_analyst(selected_analysts, "market")
                    if next_analyst:
                        self._set_agent_status(f"{next_analyst.capitalize()} Analyst", "in_progress")

                if last_seen.get("sentiment_report"):
                    self._set_agent_status("Social Analyst", "completed")
                    next_analyst = _next_selected_analyst(selected_analysts, "social")
                    if next_analyst:
                        self._set_agent_status(f"{next_analyst.capitalize()} Analyst", "in_progress")

                if last_seen.get("news_report"):
                    self._set_agent_status("News Analyst", "completed")
                    next_analyst = _next_selected_analyst(selected_analysts, "news")
                    if next_analyst:
                        self._set_agent_status(f"{next_analyst.capitalize()} Analyst", "in_progress")

                if last_seen.get("fundamentals_report"):
                    self._set_agent_status("Fundamentals Analyst", "completed")
                    for agent in ("Bull Researcher", "Bear Researcher", "Research Manager", "Trader"):
                        if self.agent_status.get(agent) == "pending":
                            self._set_agent_status(agent, "in_progress")

                if last_seen.get("investment_plan"):
                    self._set_agent_status("Research Manager", "completed")
                    self._set_agent_status("Trader", "in_progress")

                if last_seen.get("trader_investment_plan"):
                    self._set_agent_status("Trader", "completed")
                    for agent in ("Risky Analyst", "Safe Analyst", "Neutral Analyst", "Risk Judge"):
                        if self.agent_status.get(agent) == "pending":
                            self._set_agent_status(agent, "in_progress")

                if last_seen.get("final_trade_decision"):
                    self.final_trade_decision = last_seen["final_trade_decision"]
                    self._set_agent_status("Risk Judge", "completed")

            # Completed
            self.status = "completed" if not self.error else "error"
            self.emit("final", {"status": self.status, "final_trade_decision": self.final_trade_decision})

        except Exception as exc:
            self.status = "error"
            self.error = str(exc)
            self.emit("error", {"message": str(exc)})
            self.emit("final", {"status": self.status, "final_trade_decision": self.final_trade_decision})


def _queue_put_nowait_drop_oldest(queue: asyncio.Queue, item: Any) -> None:
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            pass


def _next_selected_analyst(selected: list[str], current: str) -> str | None:
    try:
        idx = selected.index(current)
    except ValueError:
        return None
    if idx + 1 >= len(selected):
        return None
    return selected[idx + 1]


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, RunSession] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def create_run(self, request: RunCreateRequest) -> RunSession:
        run_id = uuid.uuid4().hex
        session = RunSession(run_id=run_id, request=request)
        if self._loop is not None:
            session.set_loop(self._loop)

        with self._lock:
            self._runs[run_id] = session

        # Start background thread
        t = threading.Thread(target=session.run, name=f"run-{run_id}", daemon=True)
        t.start()
        return session

    def get_run(self, run_id: str) -> RunSession | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> list[RunSummary]:
        with self._lock:
            sessions = list(self._runs.values())
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return [
            RunSummary(
                run_id=s.run_id,
                created_at=s.created_at,
                status=s.status,
                ticker=s.request.ticker,
                analysis_date=s.request.analysis_date,
                research_depth=s.request.research_depth,
            )
            for s in sessions
        ]
