"""Host side of teel's guest protocol: the request/response bytes and dispatch.

This mirrors teel's `wire.py` and `host.Dispatcher` so the host needs no teel
install; only the guest (inside `python.wasm`) runs teel. The byte format is
compact JSON:

    request:  {"args": [...], "kwargs": {...}, "name": "..."}
    response: {"ok": <value>} | {"error": {"type": "...", "message": "..."}}
"""

from __future__ import annotations

import itertools
import json
import logging
import queue
from concurrent.futures import Future, ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def encode_result(value: Any) -> bytes:
    """Encode a successful host-function result."""
    return _dumps({"ok": value})


def encode_error(exc: BaseException) -> bytes:
    """Encode a host-function failure; the guest raises it as `HostError`."""
    return _dumps({"error": {"type": type(exc).__name__, "message": str(exc)}})


class Dispatcher:
    """Runs guest requests on a thread pool and queues their responses.

    `functions` is read on every request, so entries can be added or removed
    while the guest runs.
    """

    def __init__(self, *, max_workers: int | None = None) -> None:
        """Start an empty dispatcher."""
        self.functions: dict[str, Callable[..., Any]] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="teel-host"
        )
        self._tokens = itertools.count()
        self._completed: queue.SimpleQueue[tuple[int, bytes]] = queue.SimpleQueue()

    def submit(self, request: bytes) -> int:
        """Start `request` in the background and return its token."""
        token = next(self._tokens)
        future = self._executor.submit(self._run, request)
        future.add_done_callback(lambda f: self._complete(token, f))
        return token

    def next(self) -> tuple[int, bytes]:
        """Block until any submitted request (or `post`) completes."""
        return self._completed.get()

    def post(self, token: int, response: bytes) -> None:
        """Queue a response the guest did not ask for, to wake it."""
        self._completed.put((token, response))

    def close(self) -> None:
        """Stop accepting work without waiting for running calls."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, request: bytes) -> bytes:
        try:
            req = json.loads(request)
            function = self.functions[req["name"]]
            return encode_result(function(*req["args"], **req["kwargs"]))
        except Exception as exc:  # noqa: BLE001 — every failure goes back to the guest
            logger.debug("host function failed: %r", exc, exc_info=True)
            return encode_error(exc)

    def _complete(self, token: int, future: Future[bytes]) -> None:
        if not future.cancelled():
            self._completed.put((token, future.result()))
