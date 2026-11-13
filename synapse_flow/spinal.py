"""The spinal cord: deterministic DAG execution and persistent reflex arcs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Mapping

logger = logging.getLogger(__name__)
JsonObject = dict[str, Any]
_TEMPLATE = re.compile(r"^\$\{steps\.([A-Za-z0-9_-]+)((?:\.[A-Za-z0-9_-]+)*)\}$")


def normalize_intent(intent: str) -> str:
    """Normalize only inconsequential whitespace and case; matching stays deterministic."""
    return " ".join(intent.casefold().split())


@dataclass(frozen=True, slots=True)
class Action:
    """One node in a plan. ``needs`` contains ids of prerequisite nodes."""

    id: str
    synapse: str
    arguments: JsonObject = field(default_factory=dict)
    needs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id or not self.synapse:
            raise ValueError("Action id and synapse must be non-empty")
        if not isinstance(self.arguments, dict):
            raise TypeError("Action arguments must be a JSON object")

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "synapse": self.synapse,
            "arguments": self.arguments,
            "needs": list(self.needs),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Action:
        needs = data.get("needs", [])
        if not isinstance(needs, list) or not all(isinstance(item, str) for item in needs):
            raise ValueError("Action needs must be a list of step ids")
        return cls(
            id=str(data["id"]),
            synapse=str(data["synapse"]),
            arguments=dict(data.get("arguments", {})),
            needs=tuple(needs),
        )


@dataclass(frozen=True, slots=True)
class Plan:
    """A directed acyclic graph produced by Cortex or reconstructed from a skill."""

    intent: str
    steps: tuple[Action, ...]
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.intent.strip() or not self.steps:
            raise ValueError("A plan requires an intent and at least one step")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Plan step ids must be unique")

    def to_dict(self) -> JsonObject:
        return {
            "intent": self.intent,
            "rationale": self.rationale,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, intent: str, data: Mapping[str, Any]) -> Plan:
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list):
            raise ValueError("LLM response must contain a steps list")
        return cls(
            intent=intent,
            steps=tuple(Action.from_dict(step) for step in raw_steps),
            rationale=str(data.get("rationale", "")),
        )


@dataclass(frozen=True, slots=True)
class StepExecution:
    """The actual action executed after review, its output, and any HITL diff."""

    action: Action
    output: JsonObject
    review_diff: str = ""


@dataclass(frozen=True, slots=True)
class Trajectory:
    """A successful execution; outputs remain in memory and are never distilled."""

    intent: str
    steps: tuple[Action, ...]
    outputs: dict[str, JsonObject]
    review_diffs: dict[str, str]
    duration_ms: float
    source: Literal["cortex", "spinal"]
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class Skill:
    """A reusable reflex arc containing deterministic actions, not observed values."""

    name: str
    intent: str
    steps: tuple[Action, ...]
    created_at: str
    metadata: JsonObject = field(default_factory=dict)

    @property
    def key(self) -> str:
        return normalize_intent(self.intent)

    def to_plan(self) -> Plan:
        return Plan(intent=self.intent, steps=self.steps, rationale="Cached spinal reflex")

    def to_dict(self) -> JsonObject:
        return {
            "name": self.name,
            "intent": self.intent,
            "steps": [step.to_dict() for step in self.steps],
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Skill:
        return cls(
            name=str(data["name"]),
            intent=str(data["intent"]),
            steps=tuple(Action.from_dict(step) for step in data["steps"]),
            created_at=str(data["created_at"]),
            metadata=dict(data.get("metadata", {})),
        )


class SkillVault:
    """JSON-backed local vault with normalized intent lookup and atomic writes."""

    def __init__(self, directory: str | Path = "skills_vault") -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, Skill] = {}
        self._lock = threading.RLock()
        self.reload()

    def reload(self) -> None:
        loaded: dict[str, Skill] = {}
        for path in sorted(self.directory.glob("*.json")):
            try:
                skill = Skill.from_dict(json.loads(path.read_text(encoding="utf-8")))
                Plan(skill.intent, skill.steps)  # Reject malformed cached reflexes early.
            except (OSError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid skill file: {path}") from exc
            loaded[skill.key] = skill
        with self._lock:
            self._skills = loaded

    def match(self, intent: str) -> Skill | None:
        with self._lock:
            return self._skills.get(normalize_intent(intent))

    def save(self, skill: Skill) -> Path:
        Plan(skill.intent, skill.steps)
        digest = hashlib.sha256(skill.key.encode("utf-8")).hexdigest()[:12]
        path = self.directory / f"{skill.name}_{digest}.json"
        temporary = path.with_suffix(".tmp")
        with self._lock:
            temporary.write_text(
                json.dumps(skill.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary.replace(path)
            self._skills[skill.key] = skill
        return path


Executor = Callable[[Action], Awaitable[StepExecution]]


class SpinalCord:
    """Execute independent DAG nodes concurrently in deterministic topological waves."""

    def __init__(self, vault: SkillVault) -> None:
        self.vault = vault

    def match(self, intent: str) -> Skill | None:
        return self.vault.match(intent)

    async def execute(
        self,
        plan: Plan,
        executor: Executor,
        source: Literal["cortex", "spinal"],
    ) -> Trajectory:
        started = time.perf_counter()
        self._validate_dependencies(plan)
        remaining = list(plan.steps)
        completed: dict[str, JsonObject] = {}
        executions: dict[str, StepExecution] = {}

        while remaining:
            ready = [step for step in remaining if all(need in completed for need in step.needs)]
            if not ready:
                raise ValueError("Plan contains a dependency cycle")

            async def run(step: Action) -> StepExecution:
                resolved = self._resolve(step.arguments, plan.intent, completed)
                execution = await executor(Action(step.id, step.synapse, resolved, step.needs))
                # Preserve reusable data-flow templates while retaining HITL modifications.
                reviewed = self._merge_review(step.arguments, resolved, execution.action.arguments)
                action = Action(step.id, step.synapse, reviewed, step.needs)
                return StepExecution(action, execution.output, execution.review_diff)

            tasks = [asyncio.create_task(run(step)) for step in ready]
            try:
                batch = await asyncio.gather(*tasks)
            except BaseException:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

            ready_ids = {step.id for step in ready}
            for execution in batch:
                completed[execution.action.id] = execution.output
                executions[execution.action.id] = execution
            remaining = [step for step in remaining if step.id not in ready_ids]

        ordered = tuple(executions[step.id].action for step in plan.steps)
        diffs = {
            step_id: execution.review_diff
            for step_id, execution in executions.items()
            if execution.review_diff
        }
        return Trajectory(
            intent=plan.intent,
            steps=ordered,
            outputs={step.id: completed[step.id] for step in plan.steps},
            review_diffs=diffs,
            duration_ms=(time.perf_counter() - started) * 1000,
            source=source,
            rationale=plan.rationale,
        )

    @staticmethod
    def _validate_dependencies(plan: Plan) -> None:
        ids = {step.id for step in plan.steps}
        for step in plan.steps:
            missing = set(step.needs) - ids
            if missing:
                raise ValueError(f"Step {step.id!r} has unknown dependencies: {sorted(missing)}")
            if step.id in step.needs:
                raise ValueError(f"Step {step.id!r} depends on itself")

    @classmethod
    def _merge_review(cls, planned: Any, resolved: Any, reviewed: Any) -> Any:
        """Reinsert unchanged templates, but keep every human-approved value change."""
        if reviewed == resolved:
            return planned
        if isinstance(planned, dict) and isinstance(resolved, dict) and isinstance(reviewed, dict):
            return {
                key: cls._merge_review(
                    planned.get(key), resolved.get(key), reviewed_value
                )
                for key, reviewed_value in reviewed.items()
            }
        if isinstance(planned, list) and isinstance(resolved, list) and isinstance(reviewed, list):
            if len(planned) == len(resolved) == len(reviewed):
                return [
                    cls._merge_review(*values)
                    for values in zip(planned, resolved, reviewed, strict=True)
                ]
        return reviewed

    @classmethod
    def _resolve(cls, value: Any, intent: str, outputs: Mapping[str, JsonObject]) -> Any:
        """Resolve whole-value templates such as ``${steps.fetch.order_id}``."""
        if isinstance(value, dict):
            return {key: cls._resolve(item, intent, outputs) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._resolve(item, intent, outputs) for item in value]
        if value == "${intent}":
            return intent
        if not isinstance(value, str) or not (match := _TEMPLATE.match(value)):
            return value

        step_id, path = match.groups()
        if step_id not in outputs:
            raise ValueError(f"Template references unavailable step: {step_id}")
        resolved: Any = outputs[step_id]
        for part in path.strip(".").split(".") if path else []:
            resolved = resolved[int(part)] if isinstance(resolved, list) else resolved[part]
        return resolved
