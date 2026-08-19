"""
run_orchestration_accelerator_example.py

Runnable example of orchestration_accelerator alone (registry + prompting),
with no model-router / project-accelerator involved -- shows what this
package provides on its own: process/step resolution from
process_registry.yaml, and prompt loading + output-contract validation via
PromptManager, against the repo's dummy config.

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


if __name__ == "__main__":
    main()
