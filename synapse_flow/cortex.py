"""The cortex: LLM planning, intent decomposition, and runtime reflection."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Awaitable, Callable, Mapping, Protocol

from .spinal import JsonObject, Plan


class LLMClient(Protocol):
    async def complete(self, prompt: str) -> str: ...


class MockLLMClient:
    """Deterministic LLM substitute; the responder receives the real planning prompt."""

    def __init__(
        self,
        responder: Callable[[str], str | Mapping[str, Any]],
        latency: float = 0.0,
    ) -> None:
        self.responder = responder
        self.latency = latency

    async def complete(self, prompt: str) -> str:
        if self.latency:
            await asyncio.sleep(self.latency)
        response = self.responder(prompt)
        if inspect.isawaitable(response):
            response = await response
        return response if isinstance(response, str) else json.dumps(response)


class Cortex:
    """Translate intent into a constrained DAG using only registered capabilities."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self.calls = 0
        self.tokens = 0

    async def plan(self, intent: str, catalog: list[JsonObject]) -> Plan:
        prompt = self._prompt(intent, catalog)
        return self._validate(intent, catalog, await self._complete(prompt))

    async def reflect(
        self,
        intent: str,
        catalog: list[JsonObject],
        previous_plan: Plan,
        error: Exception,
    ) -> Plan:
        """Feed runtime evidence back into planning instead of blindly retrying."""
        reflection = {
            "failed_plan": previous_plan.to_dict(),
            "error": {"type": type(error).__name__, "message": str(error)[:4000]},
        }
        prompt = self._prompt(intent, catalog, reflection)
        return self._validate(intent, catalog, await self._complete(prompt))

    async def _complete(self, prompt: str) -> str:
        response = await self.llm.complete(prompt)
        self.calls += 1
        # Remote clients can replace this estimate with provider-reported usage.
        self.tokens += max(1, len(prompt) // 4) + max(1, len(response) // 4)
        return response

    @staticmethod
    def _prompt(
        intent: str,
        catalog: list[JsonObject],
        reflection: JsonObject | None = None,
    ) -> str:
        instructions = (
            "You are SynapseFlow Cortex. Decompose the intent into the smallest valid DAG. "
            "Use only listed synapses. Return JSON only with keys rationale and steps. "
            "Each step has id, synapse, arguments and needs (a list of prior step ids). "
            "Use ${steps.step_id.field} for data dependencies; do not invent credentials."
        )
        payload: JsonObject = {"intent": intent, "available_synapses": catalog}
        if reflection:
            payload["reflection"] = reflection
            instructions += " Diagnose the runtime error and return a corrected plan."
        return instructions + "\n" + json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _decode(response: str) -> Mapping[str, Any]:
        text = response.strip()
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```")
            text = text.removesuffix("```").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Cortex LLM returned non-JSON output") from exc
        if not isinstance(data, dict):
            raise ValueError("Cortex response must be a JSON object")
        return data

    def _validate(self, intent: str, catalog: list[JsonObject], response: str) -> Plan:
        plan = Plan.from_dict(intent, self._decode(response))
        known = {entry["name"] for entry in catalog}
        unknown = sorted({step.synapse for step in plan.steps} - known)
        if unknown:
            raise ValueError(f"Cortex selected unregistered synapses: {unknown}")
        return plan
