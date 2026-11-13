"""The synapses: semantic mapping plus OpenAPI and MCP protocol adapters."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Mapping, Protocol

JsonObject = dict[str, Any]


class Adapter(Protocol):
    async def call(self, operation: str, payload: JsonObject) -> JsonObject: ...


class _HTTPAdapter:
    """Lazily create httpx clients so mock deployments need no network or API keys."""

    def __init__(self, client: Any = None, timeout: float = 15.0) -> None:
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout

    async def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError("Install synapseflow's httpx dependency for remote synapses") from exc
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


class OpenAPIAdapter(_HTTPAdapter):
    """Call ``METHOD /path`` operations using JSON bodies or GET query parameters."""

    def __init__(self, base_url: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")

    async def call(self, operation: str, payload: JsonObject) -> JsonObject:
        method, path = operation.split(" ", 1)
        client = await self._get_client()
        request: dict[str, Any] = {"params": payload} if method.upper() == "GET" else {"json": payload}
        response = await client.request(method.upper(), f"{self.base_url}/{path.lstrip('/')}", **request)
        response.raise_for_status()
        if response.status_code == 204:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"result": data}


class MCPAdapter(_HTTPAdapter):
    """Minimal JSON-RPC client for the Model Context Protocol ``tools/call`` method."""

    def __init__(self, endpoint: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.endpoint = endpoint

    async def call(self, operation: str, payload: JsonObject) -> JsonObject:
        client = await self._get_client()
        response = await client.post(
            self.endpoint,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": operation, "arguments": payload},
            },
        )
        response.raise_for_status()
        envelope = response.json()
        if "error" in envelope:
            raise RuntimeError(f"MCP error: {envelope['error']}")
        result = envelope.get("result", {})
        if result.get("isError"):
            raise RuntimeError(f"MCP tool failed: {result}")
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            text = content[0].get("text", "")
            try:
                decoded = json.loads(text)
                return decoded if isinstance(decoded, dict) else {"result": decoded}
            except json.JSONDecodeError:
                return {"text": text}
        return result


class MockAdapter:
    """In-memory adapter used by tests and demonstrations of either protocol."""

    def __init__(self, handler: Callable[[JsonObject], Awaitable[JsonObject]]) -> None:
        self.handler = handler

    async def call(self, operation: str, payload: JsonObject) -> JsonObject:
        return await self.handler(payload)


def _set_path(target: JsonObject, path: str, value: Any) -> None:
    parts = path.split(".")
    cursor = target
    for part in parts[:-1]:
        child = cursor.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError(f"Cannot map through non-object field: {part}")
        cursor = child
    cursor[parts[-1]] = value


def _get_path(source: Any, path: str) -> Any:
    value = source
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


@dataclass(frozen=True, slots=True)
class Synapse:
    """A capability with protocol-independent semantic input and output contracts."""

    name: str
    protocol: Literal["openapi", "mcp"]
    description: str
    operation: str
    adapter: Adapter
    input_schema: JsonObject = field(default_factory=dict)
    risk: Literal["low", "medium", "high"] = "low"
    input_mapping: dict[str, str] = field(default_factory=dict)
    output_mapping: dict[str, str] = field(default_factory=dict)

    async def invoke(self, arguments: Mapping[str, Any]) -> JsonObject:
        if self.input_mapping:
            payload: JsonObject = {}
            for local, remote in self.input_mapping.items():
                if local not in arguments:
                    raise ValueError(f"Missing argument {local!r} for {self.name}")
                _set_path(payload, remote, arguments[local])
        else:
            payload = dict(arguments)

        raw = await self.adapter.call(self.operation, payload)
        if not isinstance(raw, dict):
            raw = {"result": raw}
        if not self.output_mapping:
            return raw
        return {local: _get_path(raw, remote) for local, remote in self.output_mapping.items()}

    def catalog_entry(self) -> JsonObject:
        return {
            "name": self.name,
            "protocol": self.protocol,
            "description": self.description,
            "input_schema": self.input_schema,
            "risk": self.risk,
        }


class SynapseRegistry:
    """The capability catalog exposed to Cortex; names are stable plan references."""

    def __init__(self) -> None:
        self._synapses: dict[str, Synapse] = {}

    def register(self, synapse: Synapse) -> None:
        if synapse.name in self._synapses:
            raise ValueError(f"Duplicate synapse: {synapse.name}")
        self._synapses[synapse.name] = synapse

    def get(self, name: str) -> Synapse:
        try:
            return self._synapses[name]
        except KeyError as exc:
            raise KeyError(f"Unknown synapse: {name}") from exc

    def catalog(self) -> list[JsonObject]:
        return [self._synapses[name].catalog_entry() for name in sorted(self._synapses)]

    async def aclose(self) -> None:
        closed: set[int] = set()
        for synapse in self._synapses.values():
            adapter = synapse.adapter
            if id(adapter) in closed or not hasattr(adapter, "aclose"):
                continue
            closed.add(id(adapter))
            result = adapter.aclose()  # type: ignore[attr-defined]
            if inspect.isawaitable(result):
                await result
