"""Run directly: python examples/02_erp_crm_sync.py (no API keys required)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Support a fresh source checkout; installed packages do not need this line.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synapse_flow import (  # noqa: E402
    Cortex,
    DispatchResult,
    Guardrails,
    Hub,
    MockAdapter,
    MockLLMClient,
    ReviewDecision,
    ReviewRequest,
    Synapse,
    SynapseRegistry,
)

INTENT = "Escalate delayed order 42"


class MockHumanReviewer:
    """A deterministic HITL stand-in that approves and strengthens the ticket priority."""

    async def review(self, request: ReviewRequest) -> ReviewDecision:
        arguments = dict(request.action.arguments)
        if arguments.get("priority") == "normal":
            arguments["priority"] = "high"
        return ReviewDecision(approved=True, arguments=arguments)


def planned_response(_: str) -> dict[str, object]:
    """Return what an LLM would emit after reading Cortex's capability prompt."""
    return {
        "rationale": "Read the ERP order, then open a reviewed CRM incident.",
        "steps": [
            {
                "id": "fetch_order",
                "synapse": "erp.get_order",
                "arguments": {"order_id": "42"},
                "needs": [],
            },
            {
                "id": "create_ticket",
                "synapse": "crm.create_ticket",
                "arguments": {
                    "order_id": "${steps.fetch_order.order_id}",
                    "subject": "Delayed order",
                    "priority": "normal",
                },
                "needs": ["fetch_order"],
            },
        ],
    }


def build_hub(vault_dir: Path) -> Hub:
    registry = SynapseRegistry()

    async def get_order(payload: dict[str, object]) -> dict[str, object]:
        return {"data": {"id": payload["orderId"], "state": "delayed"}}

    async def create_ticket(payload: dict[str, object]) -> dict[str, object]:
        ticket_id = f"CRM-{payload['orderId']}"
        return {"ticket": {"id": ticket_id, "priority": payload["priority"]}}

    registry.register(
        Synapse(
            name="erp.get_order",
            protocol="openapi",
            description="Read an ERP order by its identifier.",
            operation="GET /orders/42",
            adapter=MockAdapter(get_order),
            input_schema={"order_id": "string"},
            input_mapping={"order_id": "orderId"},
            output_mapping={"order_id": "data.id", "status": "data.state"},
        )
    )
    registry.register(
        Synapse(
            name="crm.create_ticket",
            protocol="mcp",
            description="Create a customer-operations incident ticket.",
            operation="create_ticket",
            adapter=MockAdapter(create_ticket),
            input_schema={"order_id": "string", "subject": "string", "priority": "string"},
            risk="high",
            input_mapping={"order_id": "orderId", "subject": "title", "priority": "priority"},
            output_mapping={"ticket_id": "ticket.id", "priority": "ticket.priority"},
        )
    )
    cortex = Cortex(MockLLMClient(planned_response, latency=0.12))
    return Hub(registry, cortex, Guardrails(reviewer=MockHumanReviewer()), vault_dir=vault_dir)


def print_result(label: str, result: DispatchResult) -> None:
    print(
        f"{label:<10} route={result.route:<6} "
        f"latency={result.duration_ms:7.2f} ms  "
        f"llm_calls={result.llm_calls}  tokens={result.tokens}"
    )


async def main() -> None:
    # An isolated vault makes every invocation demonstrate a true first/second run.
    with tempfile.TemporaryDirectory(prefix="synapseflow_demo_") as temporary:
        vault_dir = Path(temporary) / "skills_vault"
        hub = build_hub(vault_dir)
        try:
            first = await hub.dispatch(INTENT)
            learned_files = list(vault_dir.glob("*.json"))
            saved_skill = json.loads(learned_files[0].read_text(encoding="utf-8"))

            # Recreate the hub to prove the second run loads the persisted skill, not memory.
            await hub.aclose()
            hub = build_hub(vault_dir)
            second = await hub.dispatch(INTENT)

            print("\nSynapseFlow ERP/CRM semantic sync (cold restart)")
            print_result("First run", first)
            print_result("Second run", second)
            print(f"\nLearned skill : {first.distilled_skill}")
            print(f"Vault entries : {len(learned_files)}")
            print(f"Ticket output : {second.outputs['create_ticket']}")
            print(f"Speed-up      : {first.duration_ms / second.duration_ms:.1f}x")

            assert first.route == "cortex" and first.llm_calls == 1
            assert second.route == "spinal" and second.llm_calls == 0 and second.tokens == 0
            assert len(learned_files) == 1
            ticket_step = next(step for step in saved_skill["steps"] if step["id"] == "create_ticket")
            assert ticket_step["arguments"]["order_id"] == "${steps.fetch_order.order_id}"
            assert ticket_step["arguments"]["priority"] == "high"
            assert "create_ticket" in first.trajectory.review_diffs
            assert second.outputs["create_ticket"]["priority"] == "high"
            assert second.duration_ms < first.duration_ms
        finally:
            await hub.aclose()


if __name__ == "__main__":
    asyncio.run(main())
