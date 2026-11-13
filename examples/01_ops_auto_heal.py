"""Run directly: python examples/01_ops_auto_heal.py (no API keys required)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

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

INTENT = "Auto-heal critical alert ALERT-42"


class OperationsReviewer:
    """Mock HITL gate: inspect the proposed isolation and explicitly approve it."""

    async def review(self, request: ReviewRequest) -> ReviewDecision:
        arguments = dict(request.action.arguments)
        arguments["approved"] = True
        return ReviewDecision(approved=True, arguments=arguments, reason="Incident approved")


def planned_response(_: str) -> dict[str, object]:
    return {
        "rationale": "Gather evidence, isolate only after approval, then close the loop.",
        "steps": [
            {
                "id": "read_alert",
                "synapse": "monitor.get_alert",
                "arguments": {"alert_id": "ALERT-42"},
                "needs": [],
            },
            {
                "id": "inspect_logs",
                "synapse": "logs.search",
                "arguments": {
                    "node_id": "${steps.read_alert.node_id}",
                    "query": "critical disk pressure",
                },
                "needs": ["read_alert"],
            },
            {
                "id": "isolate_node",
                "synapse": "compute.isolate_node",
                "arguments": {
                    "node_id": "${steps.read_alert.node_id}",
                    "reason": "${steps.inspect_logs.summary}",
                    "approved": False,
                },
                "needs": ["inspect_logs"],
            },
            {
                "id": "notify_team",
                "synapse": "notify.send",
                "arguments": {
                    "incident_id": "${steps.isolate_node.incident_id}",
                    "message": "${steps.isolate_node.message}",
                    "channel": "#incident-response",
                },
                "needs": ["isolate_node"],
            },
        ],
    }


def build_hub(vault_dir: Path) -> Hub:
    registry = SynapseRegistry()

    async def get_alert(payload: dict[str, object]) -> dict[str, object]:
        return {
            "alert": {
                "id": payload["alertId"],
                "nodeId": "node-42",
                "severity": "critical",
            }
        }

    async def search_logs(payload: dict[str, object]) -> dict[str, object]:
        return {
            "result": {
                "summary": f"Confirmed disk pressure on {payload['nodeId']}",
                "entries": 3,
            }
        }

    async def isolate_node(payload: dict[str, object]) -> dict[str, object]:
        if payload["approved"] is not True:
            raise RuntimeError("Isolation attempted without explicit approval")
        return {
            "incident": {
                "id": "INC-42",
                "isolated": True,
                "message": f"Node {payload['nodeId']} isolated: {payload['reason']}",
            }
        }

    async def send_notification(payload: dict[str, object]) -> dict[str, object]:
        return {
            "delivery": {
                "status": "sent",
                "channel": payload["channel"],
                "incidentId": payload["incidentId"],
            }
        }

    registry.register(
        Synapse(
            name="monitor.get_alert",
            protocol="openapi",
            description="Read a monitoring alert.",
            operation="GET /alerts/ALERT-42",
            adapter=MockAdapter(get_alert),
            input_schema={"alert_id": "string"},
            input_mapping={"alert_id": "alertId"},
            output_mapping={
                "alert_id": "alert.id",
                "node_id": "alert.nodeId",
                "severity": "alert.severity",
            },
        )
    )
    registry.register(
        Synapse(
            name="logs.search",
            protocol="mcp",
            description="Search node logs and summarize matching evidence.",
            operation="search_logs",
            adapter=MockAdapter(search_logs),
            input_schema={"node_id": "string", "query": "string"},
            input_mapping={"node_id": "nodeId", "query": "query"},
            output_mapping={"summary": "result.summary", "entries": "result.entries"},
        )
    )
    registry.register(
        Synapse(
            name="compute.isolate_node",
            protocol="openapi",
            description="Isolate a compute node from production traffic.",
            operation="POST /nodes/isolate",
            adapter=MockAdapter(isolate_node),
            input_schema={"node_id": "string", "reason": "string", "approved": "boolean"},
            risk="high",
            input_mapping={"node_id": "nodeId", "reason": "reason", "approved": "approved"},
            output_mapping={
                "incident_id": "incident.id",
                "isolated": "incident.isolated",
                "message": "incident.message",
            },
        )
    )
    registry.register(
        Synapse(
            name="notify.send",
            protocol="mcp",
            description="Send the incident result to the operations channel.",
            operation="send_notification",
            adapter=MockAdapter(send_notification),
            input_schema={"incident_id": "string", "message": "string", "channel": "string"},
            risk="medium",
            input_mapping={"incident_id": "incidentId", "message": "text", "channel": "channel"},
            output_mapping={
                "status": "delivery.status",
                "channel": "delivery.channel",
                "incident_id": "delivery.incidentId",
            },
        )
    )
    cortex = Cortex(MockLLMClient(planned_response, latency=0.08))
    return Hub(registry, cortex, Guardrails(reviewer=OperationsReviewer()), vault_dir=vault_dir)


def print_result(label: str, result: DispatchResult) -> None:
    print(
        f"{label:<10} route={result.route:<6} "
        f"latency={result.duration_ms:7.2f} ms  "
        f"llm_calls={result.llm_calls}  tokens={result.tokens}"
    )


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="synapseflow_ops_") as temporary:
        vault_dir = Path(temporary) / "skills_vault"
        hub = build_hub(vault_dir)
        try:
            first = await hub.dispatch(INTENT)
            learned_files = list(vault_dir.glob("*.json"))
            assert len(learned_files) == 1
            saved_skill = json.loads(learned_files[0].read_text(encoding="utf-8"))

            await hub.aclose()
            hub = build_hub(vault_dir)  # Cold restart: reload the JSON reflex from disk.
            second = await hub.dispatch(INTENT)

            print("\nSynapseFlow operations auto-healing")
            print_result("First run", first)
            print_result("Second run", second)
            for step_id in ("read_alert", "inspect_logs", "isolate_node", "notify_team"):
                print(f"{step_id:<14}: {second.outputs[step_id]}")

            assert first.route == "cortex" and first.llm_calls == 1
            assert second.route == "spinal" and second.llm_calls == 0 and second.tokens == 0
            assert second.outputs["isolate_node"]["isolated"] is True
            assert second.outputs["notify_team"]["status"] == "sent"
            assert "isolate_node" in first.trajectory.review_diffs
            isolate_step = next(step for step in saved_skill["steps"] if step["id"] == "isolate_node")
            assert isolate_step["arguments"]["node_id"] == "${steps.read_alert.node_id}"
            assert isolate_step["arguments"]["approved"] is True
            assert second.duration_ms < first.duration_ms
        finally:
            await hub.aclose()


if __name__ == "__main__":
    asyncio.run(main())
