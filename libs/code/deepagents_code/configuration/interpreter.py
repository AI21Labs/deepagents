"""Resolver-backed interpreter configuration snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from deepagents_code.config_manifest import _emit_ranked_diagnostics, get_option
from deepagents_code.configuration.resolver import get_config_resolver

if TYPE_CHECKING:
    from collections.abc import Mapping

    from deepagents_code.config_manifest import ConfigOption
    from deepagents_code.configuration.resolver import ConfigResolver, ResolvedValue

InterpreterBackend = Literal["quickjs", "teel"]

_BACKENDS: tuple[InterpreterBackend, ...] = ("quickjs", "teel")

_INTERPRETER_KEYS = (
    "interpreter.backend",
    "interpreter.python_wasm",
    "interpreter.timeout_seconds",
    "interpreter.memory_limit_mb",
    "interpreter.max_ptc_calls",
    "interpreter.max_result_chars",
    "interpreter.ptc",
    "interpreter.ptc_acknowledge_unsafe",
)


def _resolved_values(
    resolver: ConfigResolver,
) -> Mapping[str, ResolvedValue[object]]:
    """Resolve one consistent generation of interpreter options.

    Returns:
        Resolved values keyed by manifest option.

    Raises:
        RuntimeError: If an interpreter option is absent from the manifest.
    """
    options = tuple(get_option(key) for key in _INTERPRETER_KEYS)
    if any(option is None for option in options):
        msg = "interpreter options are missing from the configuration manifest"
        raise RuntimeError(msg)
    required = cast("tuple[ConfigOption, ...]", options)
    resolved = resolver.resolve_options(required)
    for option in required:
        _emit_ranked_diagnostics(option, resolved[option.key])
    return resolved


@dataclass(frozen=True, slots=True)
class InterpreterConfig:
    """Configuration consumed by `CodeInterpreterMiddleware`."""

    timeout_seconds: float
    memory_limit_mb: int
    max_ptc_calls: int
    max_result_chars: int
    ptc: str | bool | list[str]
    ptc_acknowledge_unsafe: bool
    backend: InterpreterBackend = "quickjs"
    """`quickjs` runs JavaScript as `js_eval`; `teel` runs Python as `py_eval`."""
    python_wasm: str | None = None
    """Path to teel's `python.wasm`; required when `backend` is `teel`."""

    def __post_init__(self) -> None:
        """Reject an unknown backend or a `teel` backend without `python.wasm`.

        Raises:
            ValueError: If the backend is unknown or `python_wasm` is missing.
        """
        if self.backend not in _BACKENDS:
            msg = (
                f"interpreter.backend must be one of {', '.join(_BACKENDS)}; "
                f"got {self.backend!r}"
            )
            raise ValueError(msg)
        if self.backend == "teel" and not self.python_wasm:
            msg = (
                "interpreter.backend='teel' requires interpreter.python_wasm "
                "(the path to teel's python.wasm)"
            )
            raise ValueError(msg)

    @classmethod
    def from_resolver(
        cls,
        resolver: ConfigResolver | None = None,
        *,
        ptc: str | list[str] | None = None,
        ptc_acknowledge_unsafe: bool = False,
    ) -> InterpreterConfig:
        """Build a snapshot from the resolver and optional server overrides.

        Args:
            resolver: Resolver generation to read. Defaults to the process resolver.
            ptc: Invocation-scoped PTC override forwarded by the server parent.
            ptc_acknowledge_unsafe: Invocation-scoped unsafe-PTC acknowledgement.

        Returns:
            Resolved interpreter configuration for one agent build.
        """
        values = _resolved_values(resolver or get_config_resolver())
        resolved_ptc = cast("str | bool | list[str]", values["interpreter.ptc"].value)
        return cls(
            timeout_seconds=cast("float", values["interpreter.timeout_seconds"].value),
            memory_limit_mb=cast("int", values["interpreter.memory_limit_mb"].value),
            max_ptc_calls=cast("int", values["interpreter.max_ptc_calls"].value),
            max_result_chars=cast("int", values["interpreter.max_result_chars"].value),
            ptc=resolved_ptc if ptc is None else ptc,
            ptc_acknowledge_unsafe=(
                ptc_acknowledge_unsafe
                or bool(values["interpreter.ptc_acknowledge_unsafe"].value)
            ),
            backend=cast(
                "InterpreterBackend",
                str(values["interpreter.backend"].value).strip().lower(),
            ),
            python_wasm=cast("str | None", values["interpreter.python_wasm"].value)
            or None,
        )
