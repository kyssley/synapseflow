"""The pain/immunity system: permissions, HITL diffs, and execution boundaries."""

from __future__ import annotations

import asyncio
import difflib
import json
from dataclasses import dataclass
from typing import Awaitable, Mapping, Protocol

from .spinal import Action
from .synapse import JsonObject, Synapse


class ActionBlocked(RuntimeError):
    """Raised when policy or a human explicitly blocks an action."""


@dataclass(frozen=True, slots=True)
class PermissionPolicy:
    """Allow all capabilities except blocked ones, or restrict to an allow-list."""

    allowed: frozenset[str] | None = None
    blocked: frozenset[str] = frozenset()

    def check(self, name: str) -> None:
        if name in self.blocked or (self.allowed is not None and name not in self.allowed):
            raise PermissionError(f"Synapse {name!r} is outside the permission boundary")


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    action: Action
    synapse: str
    risk: str

    @property
    def preview(self) -> str:
        return json.dumps(self.action.to_dict(), indent=2, ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    approved: bool
    arguments: Mapping[str, object] | None = None
    reason: str = ""


class Reviewer(Protocol):
    async def review(self, request: ReviewRequest) -> ReviewDecision: ...


class ExecutionSandbox(Protocol):
    async def run(self, call: Awaitable[JsonObject]) -> JsonObject: ...


class TimeoutSandbox:
    """Bound adapter execution time; hostile Python requires a container/process sandbox."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def run(self, call: Awaitable[JsonObject]) -> JsonObject:
        return await asyncio.wait_for(call, timeout=self.timeout)


@dataclass(frozen=True, slots=True)
class Invocation:
    action: Action
    output: JsonObject
    review_diff: str = ""


class Guardrails:
    """Review every high-risk invocation, including invocations from cached skills."""

    def __init__(
        self,
        reviewer: Reviewer | None = None,
        policy: PermissionPolicy | None = None,
        sandbox: ExecutionSandbox | None = None,
    ) -> None:
        self.reviewer = reviewer
        self.policy = policy or PermissionPolicy()
        self.sandbox = sandbox or TimeoutSandbox()

    async def invoke(self, action: Action, synapse: Synapse) -> Invocation:
        self.policy.check(action.synapse)
        reviewed, diff = await self._authorize(action, synapse)
        call = synapse.invoke(reviewed.arguments)
        output = await self.sandbox.run(call) if synapse.risk == "high" else await call
        return Invocation(action=reviewed, output=output, review_diff=diff)

    async def _authorize(self, action: Action, synapse: Synapse) -> tuple[Action, str]:
        if synapse.risk != "high":
            return action, ""
        if self.reviewer is None:
            raise ActionBlocked(f"High-risk action {action.id!r} requires a human reviewer")

        request = ReviewRequest(action=action, synapse=action.synapse, risk=synapse.risk)
        decision = await self.reviewer.review(request)
        if not decision.approved:
            raise ActionBlocked(decision.reason or f"Human blocked action {action.id!r}")
        reviewed = action
        if decision.arguments is not None:
            reviewed = Action(action.id, action.synapse, dict(decision.arguments), action.needs)
        return reviewed, self._diff(action, reviewed)

    @staticmethod
    def _diff(original: Action, reviewed: Action) -> str:
        if original == reviewed:
            return ""
        before = json.dumps(original.arguments, indent=2, sort_keys=True).splitlines(keepends=True)
        after = json.dumps(reviewed.arguments, indent=2, sort_keys=True).splitlines(keepends=True)
        return "".join(difflib.unified_diff(before, after, fromfile="planned", tofile="approved"))
