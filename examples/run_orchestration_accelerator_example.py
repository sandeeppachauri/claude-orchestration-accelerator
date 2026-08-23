"""
run_orchestration_accelerator_example.py

Runnable example of orchestration_accelerator alone (registry + prompting),
with no model-router / project-accelerator involved -- shows what this
package provides on its own: process/step resolution from
process_registry.yaml, and prompt loading + output-contract validation via
PromptManager, against the repo's dummy config. Includes both a static
example (classify.yaml, plain string input) and a dynamic/templated
example (ticket_triage.yaml, {{key}} placeholders filled from a dict).

Run from the repo root:
    python examples/run_orchestration_accelerator_example.py
"""

from __future__ import annotations

from orchestration_accelerator.prompting import PromptManager
from orchestration_accelerator.registry import get_process, get_default_step_config


def main() -> None:
    print("--- registry: resolve a defined process ---")
    process = get_process("ticketClassification")
    print(f"steps: {process['steps']}")
    for step_name, cfg in process["step_config"].items():
        print(f"  {step_name}: model={cfg['model']} fallback={cfg.get('fallback')}")

    print("\n--- registry: default step config (unknown process) ---")
    print(get_default_step_config())

    print("\n--- prompting: load classify.yaml and validate a good output ---")
    pm = PromptManager()
    cfg = pm.get("classify", filename="classify.yaml")
    print(cfg.describe())
    validated = pm.validate_output("classify", cfg, "TECHNICAL")
    print(f"validated output: {validated!r}")

    print("\n--- prompting: a contract-violating output raises OutputContractError ---")
    try:
        pm.validate_output("classify", cfg, "not-a-real-category")
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}")

    print("\n--- prompting: dynamic/templated input via ticket_triage.yaml {{key}}s ---")
    _, system_prompt, user_prompt = pm.render(
        "ticket_triage",
        {
            "ticket_id": "T-1",
            "customer_name": "Ada",
            "customer_tier": "gold",
            "body": "My invoice is wrong",
        },
        filename="ticket_triage.yaml",
    )
    print(f"rendered system_prompt: {system_prompt!r}")
    print(f"rendered user_prompt: {user_prompt!r}")


if __name__ == "__main__":
    main()
