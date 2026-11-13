"""The evolution engine: turn successful trajectories into deterministic skills."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .spinal import Skill, SkillVault, Trajectory


class Distiller:
    """Persist reviewed actions and HITL diffs, never potentially sensitive outputs."""

    def __init__(self, vault: SkillVault) -> None:
        self.vault = vault

    def distill(self, trajectory: Trajectory) -> Skill:
        slug = re.sub(r"[^a-z0-9]+", "_", trajectory.intent.casefold()).strip("_")
        skill = Skill(
            name=f"reflex_{slug[:48] or 'learned'}",
            intent=trajectory.intent,
            steps=trajectory.steps,
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "source": trajectory.source,
                "rationale": trajectory.rationale,
                "human_diffs": trajectory.review_diffs,
            },
        )
        self.vault.save(skill)
        return skill
