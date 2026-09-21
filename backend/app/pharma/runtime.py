"""Bound the existing DeerFlow agent loop to authenticated PharmaScount tools.

The graph is created per run with the upstream pure-argument factory and explicit
middleware takeover. No configured generic tools, sandbox, memory or MCP enter it.
Business authorization and evidence locator/hash validation belong to tool_handler.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

RESOURCES = Path(__file__).parent / "resources"
_CATALOG = json.loads((RESOURCES / "tool-catalog.json").read_text(encoding="utf-8"))
_REPORT_SCHEMA = json.loads((RESOURCES / "research-output.schema.json").read_text(encoding="utf-8"))
_SYSTEM_PROMPT = (RESOURCES / "research-system.md").read_text(encoding="utf-8")
_TOOL_SPECS = {item["name"]: item for item in _CATALOG["tools"]}
_REPORT_VALIDATOR = Draft202012Validator(_REPORT_SCHEMA, format_checker=FormatChecker())
_INPUT_VALIDATORS = {name: Draft202012Validator(spec["input_schema"], format_checker=FormatChecker()) for name, spec in _TOOL_SPECS.items() if name != "submit_research_draft"}
_TERMINAL_TOOLS = {"request_clarification", "submit_research_draft"}


@dataclass(frozen=True)
class RuntimeContext:
    """Construct only from authenticated server state, never request/LLM kwargs."""

    workspace_id: str
    user_id: str
    run_id: str
    scope: dict[str, Any]
    allowed_sources: tuple[str, ...] = ("ctgov", "pubmed")
    background: bool = False

    def __post_init__(self):
        if not self.workspace_id or not self.user_id or not self.run_id:
            raise ValueError("Trusted workspace, user and run are required")
        if not self.allowed_sources or not set(self.allowed_sources) <= {"ctgov", "pubmed"}:
            raise ValueError("Unsupported source scope")
        object.__setattr__(self, "scope", copy.deepcopy(self.scope))

    @property
    def thread_id(self) -> str:
        digest = hashlib.sha256(f"{self.workspace_id}\0{self.run_id}".encode()).hexdigest()
        return f"ph_{digest[:40]}"


@dataclass(frozen=True)
class RuntimeBudget:
    max_tool_calls: int = 30
    max_model_calls: int = 12
    max_records: int = 200
    timeout_seconds: float = 600
    max_tokens: int = 120_000
    max_output_tokens: int = 4096

    def __post_init__(self):
        for value in vars(self).values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Runtime budgets must be positive finite numbers")


@dataclass
class RuntimeResult:
    draft: dict[str, Any] | None = None
    stop_reason: str = "runtime_error"
    runtime_mode: str = "deerflow"
    usage: dict[str, Any] = field(default_factory=dict)
    clarification: dict[str, Any] | None = None
    error_code: str | None = None


ToolHandler = Callable[[str, dict[str, Any], RuntimeContext], Awaitable[dict[str, Any]]]
EventEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]


class _RuntimeStop(RuntimeError):
    def __init__(self, reason: str, code: str):
        self.reason = reason
        self.code = code
        super().__init__(code)


def validate_research_draft(draft: dict, context: RuntimeContext, issued_evidence_ids: set[str]) -> None:
    """Validate structure and model-visible references before business validation.

    The handler must additionally verify locator, snapshot hash, cutoff, numeric
    support, and role/ownership in the database. This function cannot approve a
    report or claim that a citation semantically supports a clinical conclusion.
    """
    if not _REPORT_VALIDATOR.is_valid(draft):
        raise ValueError("invalid_draft_schema")
    if draft["scope"] != context.scope:
        raise ValueError("scope_mismatch")
    sources = [item["source"] for item in draft["coverage"]]
    if len(sources) != len(set(sources)) or set(sources) != set(context.allowed_sources):
        raise ValueError("coverage_scope_mismatch")
    keys = [claim["claim_key"] for claim in draft["claims"]]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate_claim_key")
    if any(key not in keys for section in draft["sections"] for key in section["claim_keys"]):
        raise ValueError("unknown_claim_key")
    for claim in draft["claims"]:
        if claim["category"] == "fact" and not any(link["relation"] == "supports" for link in claim["evidence_links"]):
            raise ValueError("unsupported_fact")
        if any(link["evidence_id"] not in issued_evidence_ids for link in claim["evidence_links"]):
            raise ValueError("unissued_evidence")


def _envelope_error(code: str) -> dict:
    return {"ok": False, "data": None, "error": {"code": code, "message": "领域工具未完成；请查看来源覆盖和资料缺口。", "retryable": False}, "coverage": [], "provenance": {}}


class _Execution:
    def __init__(self, context: RuntimeContext, budget: RuntimeBudget, handler: ToolHandler, emit: EventEmitter | None, cancel: asyncio.Event):
        self.context = context
        self.budget = budget
        self.handler = handler
        self.emit = emit
        self.cancel = cancel
        self.lock = asyncio.Lock()
        self.issued: set[str] = set()
        self.reserved_records = 0
        self.result = RuntimeResult(usage={"model_calls": 0, "tool_calls": 0, "records": 0, "input_tokens": 0, "output_tokens": 0, "estimated": False, "cost": None})

    async def event(self, name: str, data: dict) -> None:
        if self.emit:
            await self.emit(name, {"run_id": self.context.run_id, "runtime_mode": self.result.runtime_mode, **data})

    def guard(self) -> None:
        if self.cancel.is_set():
            raise _RuntimeStop("user_cancelled", "user_cancelled")
        if self.result.draft is not None or self.result.clarification is not None:
            raise _RuntimeStop(self.result.stop_reason, "already_completed")

    async def invoke(self, name: str, args: dict) -> dict:
        self.guard()
        if name not in _TOOL_SPECS:
            raise _RuntimeStop("runtime_error", "tool_not_allowed")
        if name == "submit_research_draft":
            try:
                validate_research_draft(args, self.context, self.issued)
            except ValueError as exc:
                raise _RuntimeStop("runtime_error", str(exc)) from None
        elif not _INPUT_VALIDATORS[name].is_valid(args):
            raise _RuntimeStop("runtime_error", "invalid_tool_arguments")
        scoped_ids = args.get("drug_ids", [args["drug_id"]] if "drug_id" in args else [])
        if not set(scoped_ids) <= set(self.context.scope["drug_ids"]):
            raise _RuntimeStop("runtime_error", "drug_scope_mismatch")
        if name == "search_trials" and "ctgov" not in self.context.allowed_sources:
            raise _RuntimeStop("runtime_error", "source_not_allowed")
        if name == "search_publications" and "pubmed" not in self.context.allowed_sources:
            raise _RuntimeStop("runtime_error", "source_not_allowed")
        args = copy.deepcopy(args)
        reservation = 0
        async with self.lock:
            self.guard()
            if self.result.usage["tool_calls"] >= self.budget.max_tool_calls:
                raise _RuntimeStop("budget_exhausted", "tool_budget_exhausted")
            if name in {"search_trials", "search_publications"}:
                remaining = self.budget.max_records - self.result.usage["records"] - self.reserved_records
                if remaining <= 0:
                    raise _RuntimeStop("budget_exhausted", "record_budget_exhausted")
                reservation = min(args.get("limit", 20), remaining)
                args["limit"] = reservation
                self.reserved_records += reservation
            self.result.usage["tool_calls"] += 1
        await self.event("tool_started", {"tool": name})
        try:
            envelope = await self.handler(name, args, self.context)
            if not isinstance(envelope, dict) or type(envelope.get("ok")) is not bool or not {"data", "error", "coverage", "provenance"} <= envelope.keys():
                raise _RuntimeStop("runtime_error", "invalid_tool_envelope")
            # Bound source material before it enters a model request. Never emit
            # source bodies, arguments, provider errors or hidden model reasoning.
            if len(json.dumps(envelope, ensure_ascii=False)) > 100_000:
                raise _RuntimeStop("budget_exhausted", "tool_output_too_large")
            if envelope["ok"]:
                provenance = envelope.get("provenance") or {}
                self.issued.update(str(value) for value in provenance.get("evidence_ids", []))
                data = envelope.get("data") or {}
                if reservation:
                    records = data.get("record_refs", data.get("items", data.get("records", []))) if isinstance(data, dict) else data
                    count = len(records) if isinstance(records, list) else reservation
                    self.result.usage["records"] += count
                    if count > reservation:
                        raise _RuntimeStop("budget_exhausted", "record_budget_exceeded")
                if name == "submit_research_draft":
                    self.result.draft = copy.deepcopy(args)
                    self.result.stop_reason = "answered" if all(item["status"] in {"complete", "not_requested"} for item in args["coverage"]) and not args["unanswered_questions"] else "insufficient_evidence"
                elif name == "request_clarification":
                    self.result.clarification = args
                    self.result.stop_reason = "insufficient_evidence"
            elif name in _TERMINAL_TOOLS:
                self.result.error_code = "draft_rejected" if name == "submit_research_draft" else "clarification_rejected"
            await self.event("tool_completed", {"tool": name, "ok": envelope["ok"], "evidence_ids": sorted(self.issued)})
            return envelope
        except _RuntimeStop:
            raise
        except asyncio.CancelledError:
            raise
        except Exception:
            # Provider and database exception strings can contain credentials or
            # raw source payloads. The business handler owns detailed safe audit.
            await self.event("tool_completed", {"tool": name, "ok": False, "error_code": "tool_unavailable"})
            return _envelope_error("tool_unavailable")
        finally:
            async with self.lock:
                self.reserved_records -= reservation

    def tools(self) -> list[StructuredTool]:
        result = []
        for name, spec in _TOOL_SPECS.items():
            # Each closure captures its own tool name and this run's context.
            def bind(tool_name):
                async def invoke(**kwargs):
                    return await self.invoke(tool_name, kwargs)

                return invoke

            schema = copy.deepcopy(spec["input_schema"])
            if name == "submit_research_draft":
                schema = copy.deepcopy(_REPORT_SCHEMA["$defs"]["ResearchOutput"])
                schema["$defs"] = copy.deepcopy(_REPORT_SCHEMA["$defs"])
            result.append(
                StructuredTool.from_function(
                    coroutine=bind(name),
                    name=name,
                    description=spec["output_contract"],
                    args_schema=schema,
                    infer_schema=False,
                    return_direct=name in _TERMINAL_TOOLS,
                )
            )
        return result


class _BudgetMiddleware(AgentMiddleware):
    """Budget hooks around upstream model execution; this is not a model loop."""

    def __init__(self, execution: _Execution):
        self.execution = execution

    async def awrap_model_call(self, request, handler):
        run = self.execution
        run.guard()
        usage = run.result.usage
        if usage["model_calls"] >= run.budget.max_model_calls:
            raise _RuntimeStop("budget_exhausted", "model_budget_exhausted")
        payload_chars = sum(len(str(message.content)) for message in request.messages) + len(_SYSTEM_PROMPT) + len(json.dumps(_CATALOG))
        estimated_input = max(1, math.ceil(payload_chars / 3))
        reservation = estimated_input + run.budget.max_output_tokens
        if usage["input_tokens"] + usage["output_tokens"] + reservation > run.budget.max_tokens:
            raise _RuntimeStop("budget_exhausted", "token_budget_exhausted")
        usage["model_calls"] += 1
        await run.event("model_started", {"model_call": usage["model_calls"]})
        try:
            response = await handler(request)
        except BaseException:
            # A timed-out/cancelled provider call may still incur usage. Record
            # the reservation as estimated; never report an unknown call as zero.
            usage["estimated"] = True
            usage["input_tokens"] += estimated_input
            usage["output_tokens"] += run.budget.max_output_tokens
            raise
        messages = getattr(response, "result", [response])
        metadata = [message.usage_metadata for message in messages if getattr(message, "usage_metadata", None)]
        if metadata:
            usage["input_tokens"] += sum(item.get("input_tokens", 0) for item in metadata)
            usage["output_tokens"] += sum(item.get("output_tokens", 0) for item in metadata)
        else:
            usage["estimated"] = True
            usage["input_tokens"] += estimated_input
            usage["output_tokens"] += max(1, math.ceil(sum(len(str(message.content)) + len(str(getattr(message, "tool_calls", []))) for message in messages) / 3))
        if usage["input_tokens"] + usage["output_tokens"] > run.budget.max_tokens:
            raise _RuntimeStop("budget_exhausted", "token_budget_exhausted")
        return response


class DeerFlowRuntimeAdapter:
    """One upstream graph per run; no mutation of process-global run context."""

    def __init__(self, model_name: str | None = None, *, model=None):
        self.model_name = model_name
        self._model = model
        self._running: dict[str, asyncio.Event] = {}

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {"runtime_mode": "deerflow", "custom_tools": True, "trusted_context": True, "cancellation": True, "checkpoint_recovery": False, "subagents": False, "dangerous_tools_disabled": True}

    @staticmethod
    def recover(run_id: str, checkpoint_ref: str | None = None) -> dict[str, str]:
        return {"run_id": run_id, "status": "recovery_required", "reason": "Durable checkpoint resume is not enabled; start an explicit new attempt."}

    def cancel(self, run_id: str) -> bool:
        event = self._running.get(run_id)
        if event is None:
            return False
        event.set()
        return True

    async def run(
        self,
        *,
        context: RuntimeContext,
        question: str,
        tool_handler: ToolHandler,
        emit: EventEmitter | None = None,
        budget: RuntimeBudget | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> RuntimeResult:
        budget = budget or RuntimeBudget()
        cancel = cancel_event or asyncio.Event()
        execution = _Execution(context, budget, tool_handler, emit, cancel)
        if context.run_id in self._running:
            execution.result.error_code = "run_already_active"
            return execution.result
        self._running[context.run_id] = cancel
        graph_task = cancel_task = None
        try:
            execution.guard()
            try:
                from deerflow.models.factory import create_chat_model

                model = self._model or create_chat_model(name=self.model_name, thinking_enabled=False, attach_tracing=False, model_overrides={"max_tokens": budget.max_output_tokens, "max_retries": 0})
            except Exception:
                execution.result.error_code = "model_unavailable"
                return execution.result
            from deerflow.agents.factory import create_deerflow_agent

            graph = create_deerflow_agent(model=model, tools=execution.tools(), system_prompt=_SYSTEM_PROMPT, middleware=[_BudgetMiddleware(execution)], name="pharmascope")
            # Scope and user text remain low-priority data. Auth IDs never enter
            # the model prompt and cannot be rewritten by a model tool argument.
            content = json.dumps({"question": question, "scope": context.scope, "allowed_sources": context.allowed_sources, "background": context.background}, ensure_ascii=False)
            config = {"configurable": {"thread_id": context.thread_id, "run_id": context.run_id}, "recursion_limit": budget.max_model_calls * 4 + 10}
            graph_task = asyncio.create_task(graph.ainvoke({"messages": [HumanMessage(content=content)]}, config=config))
            cancel_task = asyncio.create_task(cancel.wait())
            done, _ = await asyncio.wait({graph_task, cancel_task}, timeout=budget.timeout_seconds, return_when=asyncio.FIRST_COMPLETED)
            if cancel_task in done:
                raise _RuntimeStop("user_cancelled", "user_cancelled")
            if graph_task not in done:
                raise _RuntimeStop("budget_exhausted", "wall_clock_exhausted")
            await graph_task
            if execution.result.draft is None and execution.result.clarification is None and not execution.result.error_code:
                execution.result.error_code = "draft_not_submitted"
        except _RuntimeStop as exc:
            execution.result.stop_reason = exc.reason
            execution.result.error_code = exc.code
            if exc.reason == "user_cancelled":
                execution.result.draft = None
        except asyncio.CancelledError:
            cancel.set()
            raise
        except Exception:
            execution.result.error_code = "runtime_failure"
        finally:
            pending = [task for task in (graph_task, cancel_task) if task is not None]
            for task in pending:
                if not task.done():
                    task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            self._running.pop(context.run_id, None)
        return execution.result


class ReplayRuntimeAdapter:
    """Explicit fixture replay. Never used as a fallback for a live failure."""

    def __init__(self, draft: dict[str, Any], *, evidence_ids: list[str]):
        self.draft = copy.deepcopy(draft)
        self.evidence_ids = list(evidence_ids)

    async def run(
        self,
        *,
        context: RuntimeContext,
        question: str,
        tool_handler: ToolHandler,
        emit: EventEmitter | None = None,
        budget: RuntimeBudget | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> RuntimeResult:
        execution = _Execution(context, budget or RuntimeBudget(), tool_handler, emit, cancel_event or asyncio.Event())
        execution.result.runtime_mode = "replay"
        try:
            async with asyncio.timeout(execution.budget.timeout_seconds):
                for offset in range(0, len(self.evidence_ids), 10):
                    await execution.invoke("inspect_evidence", {"evidence_ids": self.evidence_ids[offset : offset + 10]})
                await execution.invoke("submit_research_draft", self.draft)
        except _RuntimeStop as exc:
            execution.result.stop_reason = exc.reason
            execution.result.error_code = exc.code
        except TimeoutError:
            execution.result.stop_reason = "budget_exhausted"
            execution.result.error_code = "wall_clock_exhausted"
        return execution.result
