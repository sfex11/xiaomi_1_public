"""Agent Adapter pattern — abstract base + factory.

Every supported agent runtime (OpenClaw, Hermes, generic OpenAI-compatible)
implements the AgentAdapter interface so the rest of Chatub can talk to any
backend through a single contract.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

log = logging.getLogger("adapters")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass
class ProbeResult:
    """Returned by adapter.probe() — connection test + capability detection."""
    reachable: bool
    kind: str = "unknown"
    version: str | None = None
    agents: list[str] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)
    error: str | None = None


@dataclass
class HealthStatus:
    """Returned by adapter.health() — lightweight liveness + state."""
    online: bool
    state: str = "error"          # idle | working | speaking | tool_calling | error
    version: str | None = None
    agents: list[str] | None = None


@dataclass
class AgentResponse:
    """Returned by adapter.send_message() for non-streaming calls."""
    content: str = ""
    model: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class AgentAdapter(ABC):
    """Interface every agent runtime adapter must implement."""

    kind: str = "unknown"

    @abstractmethod
    async def probe(self, url: str, token: str) -> ProbeResult:
        """Test connectivity and auto-detect capabilities."""

    @abstractmethod
    async def health(self, url: str, token: str) -> HealthStatus:
        """Lightweight health check + 5-state classification."""

    @abstractmethod
    async def send_message(
        self,
        url: str,
        token: str,
        messages: list[dict],
        *,
        stream: bool = False,
        **kwargs,
    ) -> AgentResponse | AsyncIterator[dict]:
        """Send a chat completion request.

        When *stream=False* returns an AgentResponse.
        When *stream=True* returns an async iterator yielding dicts:
            {"type": "chunk", "content": "..."}
            {"type": "done", "content": "full text", "model": "...", "usage": {...}}
        """

    @abstractmethod
    async def list_models(self, url: str, token: str) -> list[dict]:
        """Return model/agent list from the runtime."""

    @abstractmethod
    async def list_sessions(self, url: str, token: str) -> list[dict]:
        """Return active sessions (if supported)."""

    @abstractmethod
    async def get_capabilities(self, url: str, token: str) -> dict[str, bool]:
        """Return detected capability flags."""


# ---------------------------------------------------------------------------
# Registry + factory
# ---------------------------------------------------------------------------

_ADAPTERS: dict[str, type[AgentAdapter]] = {}


def register_adapter(kind: str):
    """Class decorator — registers an adapter under *kind*."""
    def wrapper(cls: type[AgentAdapter]):
        cls.kind = kind
        _ADAPTERS[kind] = cls
        return cls
    return wrapper


def create_adapter(kind: str = "openclaw") -> AgentAdapter:
    """Instantiate an adapter by *kind*.  Defaults to ``"openclaw"``."""
    cls = _ADAPTERS.get(kind)
    if cls is None:
        raise ValueError(f"Unknown adapter kind: {kind!r}  (registered: {list(_ADAPTERS)})")
    return cls()


def available_adapters() -> list[str]:
    """Return registered adapter kind strings."""
    return list(_ADAPTERS.keys())


# Auto-import concrete adapters so they self-register via @register_adapter
from adapters import openclaw as _  # noqa: F401, E402
