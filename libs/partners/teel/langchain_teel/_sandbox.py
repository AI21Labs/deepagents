"""One sandboxed CPython (`python.wasm`) instance, driven over teel's host ABI.

The guest runs `_guest/repl.py` on a dedicated host thread and pulls each
request through the `repl.next` host function. Host functions run on a
`Dispatcher` thread pool, so the guest's lookahead can keep several tool calls
in flight while it blocks on one. Teel itself only runs in the guest: the WASI
build ships it in the guest's site-packages.

The guest imports three functions from the `teel` wasm module (see teel's
`_host.c`); the host only reads guest memory it is pointed at and writes into
buffers the guest provides:

    submit(req_ptr, req_len) -> token
    next(token_out_ptr)      -> response length (blocks)
    read(buf_ptr, buf_len)   -> bytes copied
"""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import queue
import struct
import tempfile
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING, Any

import wasmtime

from langchain_teel._protocol import Dispatcher, encode_result

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_GUEST_DIR = Path(__file__).parent / "_guest"
_GUEST_SCRIPT = "/guest/repl.py"
_NEXT_FUNCTION = "repl.next"

# wasmtime-py cannot raise its async stack size (2 MiB), which caps this.
_MAX_WASM_STACK = 2 * 1024 * 1024
_I32 = wasmtime.ValType.i32()
_STDERR_TAIL_CHARS = 2_000
# Delivered to a guest blocked in `next` so it notices an interrupt; no guest
# request ever gets this token.
_WAKE_TOKEN = -1
_JOIN_TIMEOUT = 1.0


class SandboxError(Exception):
    """The guest interpreter stopped; its REPL state is gone."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def check_python_wasm(path: str | os.PathLike[str]) -> Path:
    """Return `path` as a `Path`, failing early if it is not a file.

    Raises:
        ValueError: If `path` does not exist or is not a file.
    """
    python_wasm = Path(path).expanduser()
    if not python_wasm.is_file():
        msg = (
            f"python.wasm not found at {python_wasm}. Build it with teel's "
            "`wasm/build.sh` (with `WASI_VFS_PATH` set, so the stdlib is embedded)."
        )
        raise ValueError(msg)
    return python_wasm


def _engine_config() -> wasmtime.Config:
    config = wasmtime.Config()
    config.max_wasm_stack = _MAX_WASM_STACK
    config.epoch_interruption = True
    return config


@functools.cache
def _precompiled(python_wasm: Path) -> bytes:
    """Compile `python.wasm` once per process; each sandbox deserializes it."""
    engine = wasmtime.Engine(_engine_config())
    return bytes(wasmtime.Module.from_file(engine, str(python_wasm)).serialize())


class _ComputeBudget:
    """Calls `on_expire` once the guest has run longer than its budget.

    Only guest compute counts: the clock pauses while the guest is blocked on
    the host, so slow tools and subagents never trip the timeout.
    """

    def __init__(self, on_expire: Callable[[], None]) -> None:
        self._on_expire = on_expire
        self._cond = threading.Condition()
        self._remaining: float | None = None
        self._deadline: float | None = None
        self._closed = False
        threading.Thread(target=self._watch, daemon=True, name="teel-budget").start()

    def start(self, seconds: float | None) -> None:
        with self._cond:
            self._remaining, self._deadline = seconds, None

    def stop(self) -> None:
        self.start(None)

    def resume(self) -> None:
        with self._cond:
            if self._remaining is not None and self._deadline is None:
                self._deadline = time.monotonic() + self._remaining
                self._cond.notify()

    def pause(self) -> None:
        with self._cond:
            if self._deadline is not None:
                self._remaining = max(0.0, self._deadline - time.monotonic())
                self._deadline = None

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify()

    def _watch(self) -> None:
        with self._cond:
            while not self._closed:
                if self._deadline is None:
                    self._cond.wait()
                    continue
                delay = self._deadline - time.monotonic()
                if delay > 0:
                    self._cond.wait(delay)
                    continue
                self._remaining = self._deadline = None
                self._on_expire()


class _HostImports:
    """The `teel` wasm imports, backed by a `Dispatcher`."""

    def __init__(self, dispatcher: Dispatcher, budget: _ComputeBudget) -> None:
        self._dispatcher = dispatcher
        self._budget = budget
        self._response: bytes | None = None

    @staticmethod
    def _memory(caller: wasmtime.Caller) -> wasmtime.Memory:
        memory = caller.get("memory")
        if not isinstance(memory, wasmtime.Memory):
            msg = "guest exports no memory"
            raise wasmtime.WasmtimeError(msg)
        return memory

    def submit(self, caller: wasmtime.Caller, ptr: int, length: int) -> int:
        request = bytes(self._memory(caller).read(caller, ptr, ptr + length))
        return self._dispatcher.submit(request)

    def next(self, caller: wasmtime.Caller, token_out: int) -> int:
        self._budget.pause()
        try:
            token, self._response = self._dispatcher.next()
        finally:
            self._budget.resume()
        self._memory(caller).write(caller, struct.pack("<i", token), token_out)
        return len(self._response)

    def read(self, caller: wasmtime.Caller, ptr: int, length: int) -> int:
        if self._response is None:
            return -1
        chunk, self._response = self._response[:length], None
        self._memory(caller).write(caller, chunk, ptr)
        return len(chunk)

    def define(self, linker: wasmtime.Linker) -> None:
        for name, params in (("submit", 2), ("next", 1), ("read", 2)):
            linker.define_func(
                "teel",
                name,
                wasmtime.FuncType([_I32] * params, [_I32]),
                getattr(self, name),
                access_caller=True,
            )


class Sandbox:
    """A running guest REPL. Requests are served one at a time.

    Host functions are looked up by name on each call, so `set_function` and
    `remove_function` take effect for the next guest call.
    """

    def __init__(
        self,
        python_wasm: Path,
        *,
        memory_limit: int,
        max_workers: int | None = None,
    ) -> None:
        """Instantiate `python.wasm` and start the guest REPL thread."""
        self._requests: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._pending: Future[dict[str, Any]] | None = None
        self._error: SandboxError | None = None
        self._timed_out = False
        self._closing = False

        self._dispatcher = Dispatcher(max_workers=max_workers)
        self._dispatcher.functions[_NEXT_FUNCTION] = self._next_request
        self._engine = wasmtime.Engine(_engine_config())
        self._budget = _ComputeBudget(self._interrupt)
        fd, stderr_path = tempfile.mkstemp(prefix="teel-guest-", suffix=".log")
        os.close(fd)
        self._stderr_path = Path(stderr_path)

        store = wasmtime.Store(self._engine)
        store.set_limits(memory_size=memory_limit)
        # The epoch only advances to interrupt this guest (see `_interrupt`).
        store.set_epoch_deadline(1)
        store.set_wasi(self._wasi_config())
        linker = wasmtime.Linker(self._engine)
        linker.define_wasi()
        _HostImports(self._dispatcher, self._budget).define(linker)
        module = wasmtime.Module.deserialize(self._engine, _precompiled(python_wasm))
        start = linker.instantiate(store, module).exports(store)["_start"]
        self._thread = threading.Thread(
            target=self._run_guest, args=(store, start), daemon=True, name="teel-guest"
        )
        self._thread.start()

    def _wasi_config(self) -> wasmtime.WasiConfig:
        # The stdlib is embedded in `python.wasm`; only the guest script is mounted.
        wasi = wasmtime.WasiConfig()
        wasi.argv = ["python", _GUEST_SCRIPT]
        wasi.env = [("PYTHONDONTWRITEBYTECODE", "1")]
        wasi.stderr_file = str(self._stderr_path)
        wasi.preopen_dir(str(_GUEST_DIR), "/guest", fs_mutable=False)
        return wasi

    @property
    def alive(self) -> bool:
        """Whether the guest can still serve requests."""
        return self._error is None and not self._closing

    def set_function(self, name: str, function: Callable[..., Any]) -> None:
        """Serve the host function `name` with `function`."""
        self._dispatcher.functions[name] = function

    def remove_function(self, name: str) -> None:
        """Stop serving the host function `name`."""
        self._dispatcher.functions.pop(name, None)

    def request(
        self, payload: dict[str, Any], *, timeout: float | None
    ) -> dict[str, Any]:
        """Send one request to the guest and wait for its outcome.

        Args:
            payload: The request `_guest/repl.py` reads.
            timeout: Seconds of guest compute allowed; `None` disables it.

        Raises:
            SandboxError: If the guest timed out or crashed; it is unusable after.
        """
        future: Future[dict[str, Any]] = Future()
        with self._lock:
            if self._error is not None:
                raise self._error
            self._pending = future
        self._budget.start(timeout)
        self._requests.put(payload)
        try:
            return future.result()
        finally:
            self._budget.stop()
            with self._lock:
                self._pending = None

    def _next_request(self, outcome: dict[str, Any] | None) -> dict[str, Any]:
        """Host side of `repl.next`: hand back an outcome, wait for work."""
        with self._lock:
            pending = self._pending
        if pending is not None and outcome is not None and not pending.done():
            pending.set_result(outcome)
        return self._requests.get()

    def _interrupt(self) -> None:
        """Trap the guest at its next epoch check, even if blocked on the host."""
        self._timed_out = not self._closing
        self._engine.increment_epoch()
        self._dispatcher.post(_WAKE_TOKEN, encode_result(None))

    def _run_guest(self, store: wasmtime.Store, start: wasmtime.Func) -> None:
        try:
            start(store)
        except wasmtime.ExitTrap as exc:
            error = SandboxError("SandboxCrashed", f"guest exited ({exc.code})")
        except (wasmtime.Trap, wasmtime.WasmtimeError) as exc:
            # The first line is the trap kind, e.g. a stack overflow.
            error = SandboxError("SandboxCrashed", str(exc).splitlines()[0])
        else:
            error = SandboxError("SandboxCrashed", "guest exited")
        if self._timed_out:
            error = SandboxError("Timeout", "eval exceeded its compute timeout")
        elif not self._closing:
            logger.warning(
                "teel guest stopped: %s\n%s", error.message, self._stderr_tail()
            )
        with self._lock:
            self._error = error
            pending = self._pending
        if pending is not None and not pending.done():
            pending.set_exception(error)

    def _stderr_tail(self) -> str:
        try:
            return self._stderr_path.read_text(errors="replace")[-_STDERR_TAIL_CHARS:]
        except OSError:
            return ""

    def close(self) -> None:
        """Stop the guest without waiting for in-flight host calls."""
        if self._closing:
            return
        self._closing = True
        self._interrupt()
        self._requests.put({"exit": True})
        self._thread.join(_JOIN_TIMEOUT)
        self._budget.close()
        self._dispatcher.close()
        with contextlib.suppress(OSError):
            self._stderr_path.unlink()
