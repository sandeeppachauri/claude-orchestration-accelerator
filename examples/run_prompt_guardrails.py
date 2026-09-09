"""
run_prompt_guardrails.py

Runnable example of prompt_guardrails (see
.claude/rules/prompt-guardrails.md) -- a reusable, named prompt-content
policy block (dos/don'ts) composed into a prompt's system_prompt text at
load time, resolved against config/prompt_guardrails.yaml. Unrelated to
config/guardrails.yaml's `guardrails:` step key (tool-call enforcement
via PreToolUse hooks) -- see .claude/rules/guardrails-registry.md for
that, a separate, independent mechanism.

Demonstrates templatingDemo.supportReply: prompts/support_reply.yaml
sets `prompt_guardrails: [insuranceSupportPolicy]`, so every reply this
step drafts is bound by config/prompt_guardrails.yaml's
`insuranceSupportPolicy` entry (only discuss offered insurance types, no
speculation, no unauthorized promises, no competitor mentions) without
that policy text being hand-copied into this one prompt file.

Needs a credential (ANTHROPIC_API_KEY env var, or an ambient `claude
login` OAuth session) resolved via claude-auth-accelerator.

Run from the repo root:
    python examples/run_prompt_guardrails.py
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from orchestration_accelerator.prompting import PromptManager
from project_accelerator import execute


def main() -> None:
    # Show the composed system_prompt (policy text appended) before
    # making any model call, so the effect of prompt_guardrails is
    # visible even without a credential configured.
    pm = PromptManager()
    cfg = pm.get("supportReply", filename="support_reply.yaml")
    print("--- composed system_prompt (prompt_guardrails applied) ---")
    print(cfg.system_prompt)
    print("--- end system_prompt ---\n")

    try:
        result = execute(
            {
                "process": "templatingDemo",
                "step": "supportReply",
                "input": {
                    "customer_message": "Do you offer pet insurance, and what's coming next year?"
                },
                "backend": "agent_sdk",
                "environment": "local",
            }
        )
    except AuthResolutionError as exc:
        print(f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.")
        return

    print(f"[supportReply] {result['supportReply']['output']}")


if __name__ == "__main__":
    main()
