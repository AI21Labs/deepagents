"""Slot-keyed sandboxed Python REPLs and the host functions they call.

Kept separate from `middleware.py` so the REPL mechanics stay testable
without constructing an agent or wiring up LangGraph state.

Each `_ThreadREPL` owns one `Sandbox` (a `python.wasm` guest). The guest
calls back into the host for `task(...)` and `tools.<name>(...)`; those
calls run on the sandbox's dispatcher threads, and coroutine tools are
scheduled onto the caller's event loop when there is one.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, get_type_hints

from langchain_core.tools.base import (
    InjectedToolCallId,
    _is_injected_arg_type,
    get_all_basemodel_annotations,
)
from langgraph.errors import GraphInterrupt
from langgraph.prebuilt.tool_node import _get_all_injected_args

from langchain_teel._format import coerce_tool_output_for_ptc
from langchain_teel._prompt import ptc_attribute_name
from langchain_teel._sandbox import Sandbox, SandboxError
from langchain_teel._subagent import (
    call_subagent_task_tool,
    find_subagent_task_tool,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine, Sequence
    from pathlib import Path

    from langchain_core.tools import BaseTool
    from langgraph.prebuilt import ToolRuntime

logger = logging.getLogger(__name__)

# Bounds concurrent host calls (real and speculative) per REPL.
_MAX_HOST_WORKERS = 32
_TASK_FUNCTION_NAME = "task"
_TOOL_FUNCTION_PREFIX = "tools."
_RESTARTED_NOTE = " The interpreter was restarted; earlier state is gone."


@dataclass
class EvalOutcome:
    """Normalized result of a single REPL eval.

    Exactly one of `result` / `error` is meaningful per call; `stdout`
    is collected from `print(...)` regardless.
    """

    stdout: str = ""
    stdout_truncated_chars: int = 0
    result: str | None = None
    error_type: str | None = None
    error_message: str = ""
    error_traceback: str | None = None


@dataclass
class _EvalContext:
    """What host functions need from the eval that is currently running."""

    runtime: ToolRuntime | None
    loop: asyncio.AbstractEventLoop | None
    interrupt: GraphInterrupt | None = None


def _normalize_tool_input(tool_input: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Coerce what the model passed into `tools.X(...)` to a dict.

    A well-formed call passes one dict or keyword arguments. Guard against a
    bare string or number by wrapping it under a conventional key so the
    tool's schema validation produces an informative error.
    """
    if tool_input is None:
        return dict(kwargs)
    if isinstance(tool_input, dict):
        return {**tool_input, **kwargs}
    return {"input": tool_input, **kwargs}


def _synth_tool_call_id(tool_name: str) -> str:
    """Mint a synthetic tool_call_id for a PTC-driven tool invocation."""
    return f"ptc_{tool_name}_{uuid.uuid4().hex[:8]}"


def _inject_tool_args_for_ptc(
    tool: Any,
    payload: dict[str, Any],
    outer_runtime: Any,
    tool_call_id: str,
) -> dict[str, Any]:
    """Mirror LangGraph's `ToolNode._inject_tool_args` for PTC calls.

    LangChain tools that declare `ToolRuntime` / `InjectedState` /
    `InjectedStore` only see those values when a real `ToolNode` wires
    them in. PTC calls bypass it, so we replicate the detection logic here.
    The outer runtime (captured from the active `eval` tool invocation)
    provides state/store/context/config; `tool_call_id` is freshly minted
    per sub-call. `InjectedToolCallId` is handled separately via
    `BaseTool.arun(..., tool_call_id=...)` at the bridge site.
    """
    enriched = dict(payload)

    injected = _get_all_injected_args(tool)
    if not injected or outer_runtime is None:
        return enriched

    # Build a ToolRuntime matching the outer one but with a fresh
    # tool_call_id. `type(outer_runtime)` rather than a literal import
    # so the shape stays in lockstep with whatever langgraph ships.
    derived = type(outer_runtime)(
        state=outer_runtime.state,
        tool_call_id=tool_call_id,
        config=outer_runtime.config,
        context=outer_runtime.context,
        store=outer_runtime.store,
        stream_writer=outer_runtime.stream_writer,
        tools=outer_runtime.tools,
        execution_info=getattr(outer_runtime, "execution_info", None),
        server_info=getattr(outer_runtime, "server_info", None),
    )

    if injected.runtime:
        enriched[injected.runtime] = derived
    # InjectedState: state can be injected under one or more arg names.
    if injected.state:
        for arg_name, state_field in injected.state.items():
            if state_field:
                enriched[arg_name] = (
                    outer_runtime.state.get(state_field)
                    if isinstance(outer_runtime.state, dict)
                    else getattr(outer_runtime.state, state_field, None)
                )
            else:
                enriched[arg_name] = outer_runtime.state
    if injected.store and outer_runtime.store is not None:
        enriched[injected.store] = outer_runtime.store
    return enriched


def _tool_uses_injected_tool_call_id(tool: Any) -> bool:
    """Return whether a tool declares an injected tool call ID."""
    schema_annotations = get_all_basemodel_annotations(tool.get_input_schema())
    func = getattr(tool, "func", None) or getattr(tool, "coroutine", None)
    func_annotations = get_type_hints(func, include_extras=True) if func else {}
    return any(
        _is_injected_arg_type(type_, injected_type=InjectedToolCallId)
        for type_ in {**func_annotations, **schema_annotations}.values()
    )


def _run_on_loop(
    make_coro: Callable[[], Coroutine[Any, Any, Any]],
    loop: asyncio.AbstractEventLoop | None,
) -> Any:
    """Run a coroutine from a dispatcher thread and wait for it.

    With an outer loop (async invocation) it runs there, so callbacks and loop
    affinity match normal tool execution; otherwise on a private loop.
    """
    if loop is not None and loop.is_running():
        return asyncio.run_coroutine_threadsafe(make_coro(), loop).result()
    return asyncio.run(make_coro())


def _validate_task_args(
    description: Any, subagent_type: Any, label: Any, response_schema: Any
) -> str | None:
    """Validate `task(...)` arguments and return the normalized label."""
    if not isinstance(description, str) or not description:
        msg = "task() requires a non-empty string `description`"
        raise ValueError(msg)
    if not isinstance(subagent_type, str) or not subagent_type:
        msg = "task() requires a non-empty string `subagent_type`"
        raise ValueError(msg)
    if label is not None and not isinstance(label, str):
        msg = "task() argument `label` must be a string when provided"
        raise ValueError(msg)
    if response_schema is not None and not isinstance(response_schema, dict):
        msg = "task() argument `response_schema` must be a dict when provided"
        raise ValueError(msg)
    return (label or "").strip() or None


class _ThreadREPL:
    """One sandboxed interpreter and the host functions it can call.

    Public methods may be called from any thread; evals on one REPL never
    overlap (a second concurrent eval fails with `ConcurrentEval`).
    """

    def __init__(
        self,
        python_wasm: Path,
        *,
        memory_limit: int,
        timeout: float | None,
        capture_console: bool,
        max_stdout_chars: int,
        max_ptc_calls: int | None = 256,
        subagents_enabled: bool = True,
        speculate: bool = True,
    ) -> None:
        self._python_wasm = python_wasm
        self._memory_limit = memory_limit
        self._timeout = timeout
        self._capture_console = capture_console
        self._max_stdout_chars = max_stdout_chars
        self._max_ptc_calls = max_ptc_calls
        self._subagents_enabled = subagents_enabled
        self._speculate = speculate
        self._eval_lock = threading.Lock()
        self._sandbox: Sandbox | None = None
        self._context: _EvalContext | None = None
        # `None` until `install_tools` runs; then the guest gets a `tools`
        # global even when the exposed set is empty.
        self._tools: dict[str, BaseTool] | None = None

    def install_tools(self, tools: Sequence[BaseTool]) -> None:
        """Expose `tools` as `tools.<name>` in subsequent evals."""
        self._tools = {ptc_attribute_name(tool.name): tool for tool in tools}

    def eval(
        self,
        code: str,
        *,
        outer_runtime: ToolRuntime | None = None,
        outer_loop: asyncio.AbstractEventLoop | None = None,
    ) -> EvalOutcome:
        """Run one cell and return its outcome.

        Blocks until the cell finishes; async callers run it in a thread.

        Raises:
            GraphInterrupt: If a `task(...)` or tool call the cell made raised
                one, so the parent graph can pause.
        """
        if not self._eval_lock.acquire(blocking=False):
            return EvalOutcome(
                error_type="ConcurrentEval",
                error_message="another eval is already running in this REPL",
            )
        context = _EvalContext(runtime=outer_runtime, loop=outer_loop)
        try:
            self._context = context
            outcome = self._run(code, outer_runtime)
        finally:
            self._context = None
            self._eval_lock.release()
        if outcome.error_type == "GraphInterrupt" and context.interrupt is not None:
            raise context.interrupt
        return outcome

    def _run(self, code: str, runtime: ToolRuntime | None) -> EvalOutcome:
        sandbox = self._ensure_sandbox()
        task_tool = (
            find_subagent_task_tool(getattr(runtime, "tools", ()) or ())
            if self._subagents_enabled and runtime is not None
            else None
        )
        request = {
            "code": code,
            "task": task_tool is not None,
            "tools": None if self._tools is None else sorted(self._tools),
            "speculate": self._speculate,
            "max_ptc_calls": self._max_ptc_calls,
            "max_stdout_chars": self._max_stdout_chars if self._capture_console else 0,
        }
        try:
            raw = sandbox.request(request, timeout=self._timeout)
        except SandboxError as e:
            return EvalOutcome(
                error_type=e.error_type, error_message=e.message + _RESTARTED_NOTE
            )
        outcome = EvalOutcome(**raw)
        if not self._capture_console:
            outcome.stdout, outcome.stdout_truncated_chars = "", 0
        return outcome

    def _ensure_sandbox(self) -> Sandbox:
        """Return a live sandbox, starting a new one if the last one died."""
        sandbox = self._sandbox
        if sandbox is None or not sandbox.alive:
            if sandbox is not None:
                sandbox.close()
            sandbox = Sandbox(
                self._python_wasm,
                memory_limit=self._memory_limit,
                max_workers=_MAX_HOST_WORKERS,
            )
            sandbox.set_function(_TASK_FUNCTION_NAME, self._call_task)
            self._sandbox = sandbox
        self._sync_tool_functions(sandbox)
        return sandbox

    def _sync_tool_functions(self, sandbox: Sandbox) -> None:
        for name in self._tools or ():
            sandbox.set_function(
                f"{_TOOL_FUNCTION_PREFIX}{name}", self._tool_function(name)
            )

    def _active_context(self, function_name: str) -> _EvalContext:
        # Speculative calls can outlive the eval that predicted them.
        context = self._context
        if context is None:
            msg = f"{function_name} called outside an active eval"
            raise RuntimeError(msg)
        return context

    def _tool_function(self, name: str) -> Callable[..., Any]:
        def call(tool_input: Any = None, /, **kwargs: Any) -> Any:
            context = self._active_context(f"tools.{name}")
            tool = (self._tools or {}).get(name)
            if tool is None:
                msg = f"tool {name!r} is not exposed to the REPL"
                raise AttributeError(msg)
            call_id = _synth_tool_call_id(tool.name)
            args = _inject_tool_args_for_ptc(
                tool,
                _normalize_tool_input(tool_input, kwargs),
                context.runtime,
                call_id,
            )
            config = context.runtime.config if context.runtime is not None else None
            try:
                result = _run_on_loop(
                    lambda: tool.arun(
                        args,
                        callbacks=config.get("callbacks") if config else None,
                        run_id=uuid.uuid4(),
                        config=config,
                        tool_call_id=(
                            call_id if _tool_uses_injected_tool_call_id(tool) else None
                        ),
                    ),
                    context.loop,
                )
            except GraphInterrupt as e:
                context.interrupt = e
                raise
            return coerce_tool_output_for_ptc(result)

        return call

    def _call_task(
        self,
        description: Any = None,
        subagent_type: Any = None,
        *,
        label: Any = None,
        response_schema: Any = None,
    ) -> Any:
        context = self._active_context(_TASK_FUNCTION_NAME)
        label = _validate_task_args(description, subagent_type, label, response_schema)
        runtime = context.runtime
        task_tool = find_subagent_task_tool(getattr(runtime, "tools", ()) or ())
        if task_tool is None:
            msg = "task tool not configured for this eval"
            raise RuntimeError(msg)
        try:
            result = _run_on_loop(
                lambda: call_subagent_task_tool(
                    task_tool,
                    description=description,
                    subagent_type=subagent_type,
                    response_schema=response_schema,
                    runtime=runtime,
                    label=label,
                ),
                context.loop,
            )
        except GraphInterrupt as e:
            context.interrupt = e
            raise
        return coerce_tool_output_for_ptc(result)

    def reset(self) -> None:
        """Clear the interpreter's globals, keeping the sandbox running."""
        sandbox = self._sandbox
        if sandbox is None or not sandbox.alive:
            return
        with self._eval_lock:
            try:
                sandbox.request({"reset": True}, timeout=self._timeout)
            except SandboxError:
                logger.debug("sandbox died during reset", exc_info=True)

    def close(self) -> None:
        """Stop the sandbox."""
        if self._sandbox is not None:
            self._sandbox.close()
            self._sandbox = None


class _Registry:
    """Slot-keyed store of `_ThreadREPL`s.

    Eviction is driven externally via `evict(slot_id)`, typically from the
    middleware's `after_agent` hook. Nothing is checkpointed: a REPL lives
    only in this process's memory.
    """

    def __init__(self, python_wasm: Path, **repl_kwargs: Any) -> None:
        self._python_wasm = python_wasm
        self._repl_kwargs = repl_kwargs
        self._repls: dict[str, _ThreadREPL] = {}
        self._lock = threading.Lock()

    def get(self, slot_id: str) -> _ThreadREPL:
        with self._lock:
            repl = self._repls.get(slot_id)
            if repl is None:
                repl = self._repls[slot_id] = _ThreadREPL(
                    self._python_wasm, **self._repl_kwargs
                )
            return repl

    def get_if_exists(self, slot_id: str) -> _ThreadREPL | None:
        """Return the REPL for `slot_id` without creating one."""
        with self._lock:
            return self._repls.get(slot_id)

    def evict(self, slot_id: str) -> None:
        """Close and remove the REPL for `slot_id`. No-op if absent."""
        with self._lock:
            repl = self._repls.pop(slot_id, None)
        if repl is not None:
            repl.close()

    def reset_repl(self, slot_id: str) -> None:
        """Clear the REPL's globals for `slot_id`. No-op if absent."""
        repl = self.get_if_exists(slot_id)
        if repl is not None:
            repl.reset()

    def close(self) -> None:
        with self._lock:
            repls = list(self._repls.values())
            self._repls.clear()
        for repl in repls:
            repl.close()
