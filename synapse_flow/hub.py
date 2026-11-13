"""Central orchestrator connecting the cortex, spinal cord, and evolution engine."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .cortex import Cortex
from .distiller import Distiller
from .guardrails import ActionBlocked, Guardrails
from .spinal import Action, Skill, SkillVault, SpinalCord, StepExecution, Trajectory
from .synapse import JsonObject, SynapseRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    intent: str
    route: Literal["spinal", "cortex"]
    outputs: dict[str, JsonObject]
    duration_ms: float
    llm_calls: int
    tokens: int
    distilled_skill: str | None
    trajectory: Trajectory


class Hub:
    """Route by cost: try a local reflex first, then escalate anomalies to Cortex."""

    def __init__(
        self,
        synapses: SynapseRegistry,
        cortex: Cortex,
        guardrails: Guardrails | None = None,
        vault_dir: str | Path = "skills_vault",
        max_reflections: int = 1,
    ) -> None:
        self.synapses = synapses
        self.cortex = cortex
        self.guardrails = guardrails or Guardrails()
        self.spinal = SpinalCord(SkillVault(vault_dir))
        self.distiller = Distiller(self.spinal.vault)
        self.max_reflections = max_reflections

    async def dispatch(self, intent: str) -> DispatchResult:
        started = time.perf_counter()
        calls_before, tokens_before = self.cortex.calls, self.cortex.tokens

        skill = self.spinal.match(intent)
        if skill is not None:
            try:
                trajectory = await self.spinal.execute(skill.to_plan(), self._execute, "spinal")
                return self._result(intent, "spinal", trajectory, None, started, calls_before, tokens_before)
            except (ActionBlocked, PermissionError):
                raise  # A denied reflex must never be bypassed by autonomous replanning.
            except Exception as exc:
                logger.warning("Reflex %s failed; escalating to Cortex: %s", skill.name, exc)

        catalog = self.synapses.catalog()
        plan = await self.cortex.plan(intent, catalog)
        reflections = 0
        while True:
            try:
                trajectory = await self.spinal.execute(plan, self._execute, "cortex")
                break
            except (ActionBlocked, PermissionError):
                raise
            except Exception as exc:
                if reflections >= self.max_reflections:
                    raise
                reflections += 1
                plan = await self.cortex.reflect(intent, catalog, plan, exc)

        learned = self.distiller.distill(trajectory)
        return self._result(
            intent, "cortex", trajectory, learned, started, calls_before, tokens_before
        )

    async def _execute(self, action: Action) -> StepExecution:
        """The single execution funnel: no route can bypass policy or review."""
        invocation = await self.guardrails.invoke(action, self.synapses.get(action.synapse))
        return StepExecution(invocation.action, invocation.output, invocation.review_diff)

    def _result(
        self,
        intent: str,
        route: Literal["spinal", "cortex"],
        trajectory: Trajectory,
        skill: Skill | None,
        started: float,
        calls_before: int,
        tokens_before: int,
    ) -> DispatchResult:
        return DispatchResult(
            intent=intent,
            route=route,
            outputs=trajectory.outputs,
            duration_ms=(time.perf_counter() - started) * 1000,
            llm_calls=self.cortex.calls - calls_before,
            tokens=self.cortex.tokens - tokens_before,
            distilled_skill=skill.name if skill else None,
            trajectory=trajectory,
        )

    async def aclose(self) -> None:
        await self.synapses.aclose()
