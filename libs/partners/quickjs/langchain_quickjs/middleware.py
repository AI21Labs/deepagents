"""`CodeInterpreterMiddleware`: exposes a persistent Python REPL tool."""

import asyncio
import contextlib
import functools
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal

from deepagents.middleware._utils import append_to_system_message
from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ContextT,
    ModelRequest,
    ModelResponse,
    ResponseT,
)
from langchain.tools import BaseTool, ToolRuntime
from langchain_core._api import beta
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langgraph.runtime import Runtime

from langchain_quickjs._format import format_outcome
from langchain_quickjs._prompt import (
    render_eval_tool_code_doc,
    render_eval_tool_description,
    render_repl_system_prompt,
    render_subagent_system_prompt,
)
from langchain_quickjs._ptc import (
    PTCOption,
    filter_tools_for_ptc,
    render_ptc_prompt,
)
from langchain_quickjs._repl import EvalOutcome, _Registry
from langchain_quickjs._subagent import find_subagent_task_tool

logger = logging.getLogger(__name__)

_DEFAULT_MEMORY_LIMIT = 64 * 1024 * 1024
_DEFAULT_TIMEOUT = 5.0
_DEFAULT_MAX_PTC_CALLS = 256
_DEFAULT_MAX_RESULT_CHARS = 4_000
_DEFAULT_TOOL_NAME = "eval"

PersistenceMode = Literal["thread", "turn", "call"]


class EvalSchema(BaseModel):
    """Input schema for the `eval` tool."""

    code: str = Field(
        description=(
            "Python statement(s) to execute. The value of the final expression "
            "is returned as the result."
        ),
    )


def _resolve_mode(*, mode: str | None) -> PersistenceMode:
    """Normalize persistence mode and enforce invariant constraints."""
    match mode:
        case "thread":
            return "thread"
        case "turn":
            return "turn"
        case None | "call":
            return "call"
        case _:
            msg = "`mode` must be one of 'thread', 'turn', or 'call'."
            raise ValueError(msg)


def _resolve_thread_id(fallback: str) -> str:
    """Extract `thread_id` from langgraph config or use `fallback`.

    The fallback is a middleware-instance-scoped id: when the caller didn't
    configure a `thread_id` (common for ad-hoc `agent.invoke(...)` in tests or
    single-shot scripts), we still need all resolver calls within one
    middleware lifetime to return the same id — otherwise `wrap_model_call`
    installs tools on one REPL and the eval tool looks up a different one, and
    the model sees `NameError: tools is not defined`.
    """
    try:
        config = get_config()
    except RuntimeError:
        # Not running inside a Runnable — test / bare-call path.
        return fallback
    thread_id = config.get("configurable", {}).get("thread_id") if config else None
    if thread_id is not None:
        return str(thread_id)
    return fallback


@beta()
class CodeInterpreterMiddleware(AgentMiddleware[AgentState, ContextT, ResponseT]):
    """Middleware exposing a persistent Python REPL to the agent.

    Each LangGraph thread gets its own in-memory Python namespace, so globals
    from one conversation cannot leak into another. There is no sandboxing:
    code runs with full builtins and no timeout or memory cap. The two
    capabilities worth wiring in are exposed as ordinary synchronous functions:

    - `task(...)` — dispatch a Deep Agents subagent (when a `task` tool is
      configured and `subagents=True`).
    - `tools.<name>(...)` — call the agent's own tools (opt-in via `ptc`).

    Args:
        max_ptc_calls: Maximum number of `tools.*` bridge calls allowed during
            one `eval` execution. Exceeding this budget raises from the bridge
            before invoking the tool; uncaught overflows surface as
            `PTCCallBudgetExceeded`. `None` disables the budget. Default 256.
        tool_name: Name of the tool exposed to the model. Default `eval`.
        max_result_chars: Result and stdout blocks are independently truncated
            to this many characters before being sent back to the model.
            Stdout buffering is also bounded to this value during collection.
            Default 4000.
        capture_console: If `True`, capture `print(...)` / `stdout` output and
            emit it in a `<stdout>` block alongside the result. Default `True`.
        subagents: If `True`, expose the top-level `task(...)` function when the
            current agent has a Deep Agents `task` tool. Default `True`.
        ptc: Programmatic tool-calling config. A list of tool names and/or
            `BaseTool` instances to expose under the `tools` namespace. `None`
            disables PTC. Default `None`.
        mode: State persistence lifetime — `"thread"` (persist across turns of a
            conversation, in-memory), `"turn"` (reset between turns), or
            `"call"` (fresh namespace per `eval`). Default `"thread"`.

    Example:
        ```python
        from deepagents import create_deep_agent
        from langchain_quickjs import CodeInterpreterMiddleware

        agent = create_deep_agent(
            model="claude-sonnet-4-6",
            middleware=[CodeInterpreterMiddleware()],
        )
        ```
    """

    def __init__(
        self,
        *,
        memory_limit: int = _DEFAULT_MEMORY_LIMIT,
        timeout: float = _DEFAULT_TIMEOUT,
        max_ptc_calls: int | None = _DEFAULT_MAX_PTC_CALLS,
        tool_name: str = _DEFAULT_TOOL_NAME,
        max_result_chars: int = _DEFAULT_MAX_RESULT_CHARS,
        capture_console: bool = True,
        subagents: bool = True,
        ptc: PTCOption | None = None,
        mode: PersistenceMode | None = None,
    ) -> None:
        """Initialize REPL middleware state and build the exposed eval tool."""
        super().__init__()
        if max_ptc_calls is not None and max_ptc_calls < 1:
            msg = "`max_ptc_calls` must be >= 1 or None"
            raise ValueError(msg)
        self._max_ptc_calls = max_ptc_calls
        self._tool_name = tool_name
        self._max_result_chars = max_result_chars
        self._capture_console = capture_console
        self._subagents = subagents
        self._ptc = ptc
        self._mode = _resolve_mode(mode=mode)
        self._registry = _Registry(
            capture_console=capture_console,
            max_stdout_chars=max_result_chars,
            max_ptc_calls=max_ptc_calls,
            subagents_enabled=subagents,
        )
        self._base_prompt_cache: dict[bool, str] = {}
        self._ptc_prompt_cache: tuple[frozenset[str], str] | None = None
        self._ptc_tools_by_thread: dict[str, tuple[BaseTool, ...]] = {}
        # Stable fallback thread id — used when `thread_id` isn't in langgraph
        # config. Must be instance-scoped so `wrap_model_call` and `eval`
        # invocations within one conversation resolve to the same REPL;
        # otherwise the PTC install happens on one REPL and the eval runs on
        # another (and sees `tools` undefined).
        self._fallback_thread_id = f"session_{uuid.uuid4().hex[:8]}"
        self.tools: list[BaseTool] = [self._build_tool()]

    def _build_tool(self) -> BaseTool:
        tool_name = self._tool_name
        max_chars = self._max_result_chars
        fallback_id = self._fallback_thread_id
        middleware = self
        code_doc = render_eval_tool_code_doc(mode=self._mode)
        tool_description = render_eval_tool_description(mode=self._mode)

        def _make_tool_message(
            outcome: EvalOutcome,
            tool_call_id: str | None,
        ) -> ToolMessage:
            return ToolMessage(
                content=format_outcome(outcome, max_result_chars=max_chars),
                tool_call_id=tool_call_id,
                name=tool_name,
            )

        def sync_eval(
            runtime: ToolRuntime[None, Any],
            code: Annotated[str, code_doc],
        ) -> ToolMessage:
            thread_id = _resolve_thread_id(fallback_id)
            repl = middleware._repl_for_eval(thread_id)
            try:
                outcome = repl.eval(code, outer_runtime=runtime)
            finally:
                if middleware._mode == "call":
                    middleware._registry.reset_repl(thread_id)
            return _make_tool_message(outcome, runtime.tool_call_id)

        async def async_eval(
            runtime: ToolRuntime[None, Any],
            code: Annotated[str, code_doc],
        ) -> ToolMessage:
            thread_id = _resolve_thread_id(fallback_id)
            repl = middleware._repl_for_eval(thread_id)
            try:
                # Offload the (synchronous) exec to a worker thread so it does
                # not block the event loop; PTC/task bridges call tools
                # synchronously from that thread.
                outcome = await asyncio.to_thread(
                    functools.partial(repl.eval, code, outer_runtime=runtime)
                )
            finally:
                if middleware._mode == "call":
                    middleware._registry.reset_repl(thread_id)
            return _make_tool_message(outcome, runtime.tool_call_id)

        return StructuredTool.from_function(
            name=tool_name,
            description=tool_description,
            func=sync_eval,
            coroutine=async_eval,
            infer_schema=False,
            args_schema=EvalSchema,
            metadata={"ls_code_input_language": "python"},
        )

    def _repl_for_eval(self, thread_id: str) -> Any:
        """Return the REPL slot for one eval invocation."""
        repl = self._registry.get(thread_id)
        if self._mode == "call" and self._ptc is not None:
            repl.install_tools(list(self._ptc_tools_by_thread.get(thread_id, ())))
        return repl

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT]:
        """Inject the REPL's system-prompt snippet on every model call."""
        prompt = self._prepare_for_call(request)
        return handler(
            request.override(
                system_message=self._extend(request.system_message, prompt)
            ),
        )

    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[
            [ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]
        ],
    ) -> ModelResponse[ResponseT]:
        """(async) Inject the REPL's system-prompt snippet on every model call."""
        prompt = self._prepare_for_call(request)
        return await handler(
            request.override(
                system_message=self._extend(request.system_message, prompt)
            ),
        )

    def after_agent(
        self,
        state: AgentState,  # noqa: ARG002
        runtime: "Runtime[ContextT]",  # noqa: ARG002
    ) -> dict[str, Any] | None:
        """Evict this thread's REPL slot for non-persistent modes.

        In `thread` mode the slot stays in the registry so its namespace
        persists (in-memory) across turns. In `turn` / `call` mode the slot is
        dropped at turn end.
        """
        thread_id = _resolve_thread_id(self._fallback_thread_id)
        self._ptc_tools_by_thread.pop(thread_id, None)
        if self._mode != "thread":
            self._registry.evict(thread_id)
        return None

    def _base_prompt(self, *, ptc_attached: bool) -> str:
        """Return the base REPL system prompt, rendered lazily and memoized."""
        cached = self._base_prompt_cache.get(ptc_attached)
        if cached is None:
            cached = render_repl_system_prompt(
                tool_name=self._tool_name,
                mode=self._mode,
                ptc_attached=ptc_attached,
            )
            self._base_prompt_cache[ptc_attached] = cached
        return cached

    def _prepare_for_call(self, request: ModelRequest[ContextT]) -> str:
        """Install PTC bindings for this turn and return the prompt addendum.

        Called from both sync and async model-call wrappers. Reads the live
        tool list off the request (middlewares upstream may have filtered it),
        installs PTC bridges on the current thread's REPL, and renders matching
        API-reference text.
        """
        request_tools: list[BaseTool] = list(getattr(request, "tools", []) or [])

        subagent_section = ""
        if self._subagents and find_subagent_task_tool(request_tools) is not None:
            subagent_section = render_subagent_system_prompt(tool_name=self._tool_name)

        if self._ptc is None:
            return self._base_prompt(ptc_attached=False) + subagent_section

        exposed = filter_tools_for_ptc(
            request_tools,
            self._ptc,
            self_tool_name=self._tool_name,
        )
        prompt = self._base_prompt(ptc_attached=bool(exposed)) + subagent_section
        thread_id = _resolve_thread_id(self._fallback_thread_id)
        repl = self._registry.get(thread_id)
        repl.install_tools(exposed)
        self._ptc_tools_by_thread[thread_id] = tuple(exposed)
        # Rendering the signature block is cheap but not free; cache by the set
        # of exposed names. The set doesn't encode tool *identity* — if a tool
        # keeps its name but its schema changes between turns, the cached prompt
        # staleness is on the caller.
        exposed_names = frozenset(t.name for t in exposed)
        if self._ptc_prompt_cache is None or self._ptc_prompt_cache[0] != exposed_names:
            self._ptc_prompt_cache = (
                exposed_names,
                render_ptc_prompt(exposed, tool_name=self._tool_name),
            )
        return prompt + self._ptc_prompt_cache[1]

    def _extend(
        self, system_message: SystemMessage | None, prompt: str
    ) -> SystemMessage:
        return append_to_system_message(system_message, prompt)

    def __del__(self) -> None:
        """Best-effort registry cleanup on GC; never raises at shutdown."""
        with contextlib.suppress(Exception):
            self._registry.close()
