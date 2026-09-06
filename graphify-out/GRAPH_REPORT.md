# Graph Report - claude-orchestration-accelerator  (2026-08-26)

## Corpus Check
- Corpus is ~43,819 words - fits in a single context window. You may not need a graph.

## Summary
- 553 nodes · 932 edges · 43 communities (31 shown, 12 thin omitted)
- Extraction: 88% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 107 edges (avg confidence: 0.86)
- Token cost: 282,989 input · 0 output

## Community Hubs (Navigation)
- Ticket Classification Pipeline
- Model Router Backends
- Accelerator Stack Overview
- Process Registry Core
- Prompt Manager
- Scaffold Data Config
- Execute Core + Logging
- Batch Processing
- File Manager
- CPA Scaffold CLI
- Environment Resolution
- Batch Test Fakes
- Prompt Files + Deps
- Guardrails Engine
- Scaffold Sync Checker
- Context Mgmt: Assistant Prompt Threading
- Capability Passthrough Concepts
- Capability Registry Schema
- MCP Scope Config
- Guardrails Registry Schema
- MCP Scope Hook
- Scaffold Sync Tests
- Context Mgmt: Observability/Streaming Plan
- Auth + Guardrail Helpers
- Onboarding Prompt Files
- Scaffold Sync Docs
- MCP Server Config
- Scaffold MCP Config
- Accelerator Packages
- Pre-Tool-Use Hook
- Doc Sync Reminder Hook
- File Upload Helpers
- Git Hooks Installer
- Pre-Commit Scaffold Sync
- Scaffold Pre-Tool-Use Hook
- Scaffold Doc Sync Hook
- Claude Plugins Manifest
- Scaffold Smoke Test
- Root CLAUDE.md
- Logger Config Doc
- Scaffold test-all Command

## God Nodes (most connected - your core abstractions)
1. `PromptManager` - 27 edges
2. `execute()` - 25 edges
3. `cmd_new()` - 16 edges
4. `get_process()` - 16 edges
5. `execute_with_fallback()` - 15 edges
6. `friendly_error()` - 15 edges
7. `call_agent_sdk()` - 13 edges
8. `execute_batch()` - 13 edges
9. `get_process_by_id()` - 12 edges
10. `validate_capabilities()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `test_get_process_by_id_resolves()` --calls--> `get_process_by_id()`  [INFERRED]
  tests/test_batch_registry.py → src/orchestration_accelerator/registry/registry.py
- `Classify Prompt` --semantically_similar_to--> `Classify Prompt (scaffold_data)`  [INFERRED] [semantically similar]
  prompts/classify.yaml → project-accelerator/src/project_accelerator/scaffold_data/prompts/classify.yaml
- `Classify SOA (Respond) Prompt` --semantically_similar_to--> `Classify SOA (Respond) Prompt (scaffold_data)`  [INFERRED] [semantically similar]
  prompts/classify_soa.yaml → project-accelerator/src/project_accelerator/scaffold_data/prompts/classify_soa.yaml
- `Escalation Decision Prompt` --semantically_similar_to--> `Escalation Decision Prompt (scaffold_data)`  [INFERRED] [semantically similar]
  prompts/escalation_decision.yaml → project-accelerator/src/project_accelerator/scaffold_data/prompts/escalation_decision.yaml
- `Extract v2 Prompt` --semantically_similar_to--> `Extract v2 Prompt (scaffold_data)`  [INFERRED] [semantically similar]
  prompts/extract_v2.yaml → project-accelerator/src/project_accelerator/scaffold_data/prompts/extract_v2.yaml

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Capability passthrough validation flow** — config_process_registry_yaml, config_capability_registry_yaml, validate_capabilities_fn, unsupported_capability_error [EXTRACTED 1.00]
- **agent_sdk PreToolUse hook merge (MCP scope + guardrails + logger)** — call_agent_sdk_fn, make_mcp_scope_hook_fn, guardrails_step_key, claudesdklogger_accelerator [EXTRACTED 1.00]
- **Scaffold sync verification process** — claude_claude_md_scaffold_sync, check_scaffold_sync_script, install_git_hooks_script, claude_claude_project_accelerator [EXTRACTED 1.00]
- **Capability passthrough validation flow** — scaffold_data_claude_rules_process_registry, scaffold_data_claude_rules_capability_registry, scaffold_data_config_capability_registry_agent_sdk_allowed [EXTRACTED 0.90]
- **templatingDemo.escalate multi-mechanism opt-in example** — scaffold_data_config_process_registry_templatingdemo_escalate, scaffold_data_claude_rules_mcp_scope, scaffold_data_claude_rules_guardrails_registry [EXTRACTED 0.90]
- **batch_registry entries resolve model config via process_registry** — scaffold_data_config_batch_registry_ticketclassificationbatch, scaffold_data_config_batch_registry_ticketclassificationbatchstaging, scaffold_data_config_process_registry_ticketclassification [EXTRACTED 0.90]
- **Ticket Classification Pipeline (classify -> extract -> respond)** — prompts_classify_classify, prompts_extract_v2_extract, prompts_classify_soa_respond [INFERRED 0.90]
- **Ticket Triage-to-Escalation Pipeline** — prompts_ticket_triage_ticket_triage, prompts_escalation_decision_escalation_decision [EXTRACTED 1.00]
- **Onboarding Pipeline (welcome -> verify -> finalize)** — prompts_welcome_welcome, prompts_verify_kyc_verify, prompts_finalize_finalize [INFERRED 0.85]

## Communities (43 total, 12 thin omitted)

### Community 0 - "Ticket Classification Pipeline"
Cohesion: 0.08
Nodes (39): main(), run_ticket_classification.py Runnable example of the full stack:…, fixture, main(), run_execute_example.py Runnable example of project_accelerator's single entry…, execute_batch(), Any, Path (+31 more)

### Community 1 - "Model Router Backends"
Cohesion: 0.09
Nodes (36): main(), run_router_example.py Runnable example of execute_with_fallback(): the ordered…, call_agent_sdk(), call_messages_api(), _looks_like_rate_limit_or_overload(), _merge_hooks(), Any, Exception (+28 more)

### Community 2 - "Accelerator Stack Overview"
Cohesion: 0.06
Nodes (36): Accelerators sibling repo, auth_accelerator.build_api_credential(environment), capability passthrough, classify step, registry-reviewer agent, claude-auth-accelerator, claude-model-router-accelerator, claude-orchestration-accelerator (repo/package) (+28 more)

### Community 3 - "Process Registry Core"
Cohesion: 0.11
Nodes (37): main(), run_orchestration_accelerator_example.py Runnable example of…, friendly_error(), summary: one plain-English sentence, no jargon, safe to hand to a non-technical…, get_allowed_capabilities(), get_default_step_config(), get_process(), get_process_by_id() (+29 more)

### Community 4 - "Prompt Manager"
Cohesion: 0.09
Nodes (31): OutputContractError, PromptConfig, PromptManager, PromptValidationError, Any, Exception, Path, prompt_manager.py Promoted, near-as-is, from prompt-description-… (+23 more)

### Community 5 - "Scaffold Data Config"
Cohesion: 0.10
Nodes (35): cpa CLI, execute(payload), project-accelerator README, --sample-needed yes|no flag, scaffold_data package data, Scaffolded CLAUDE.local.md, registry-reviewer subagent, Scaffolded claude-orchestration-accelerator CLAUDE.md (+27 more)

### Community 6 - "Execute Core + Logging"
Cohesion: 0.12
Nodes (27): _ensure_project_logging_configured(), _execute_async(), _log_best_effort(), PayloadValidationError, Any, Exception, Path, core.py The master accelerator's single library entry point: execute(payload).… (+19 more)

### Community 7 - "Batch Processing"
Cohesion: 0.14
Nodes (26): BatchJobError, _client(), execute_batch(), _prompts_dir_for_registry(), Any, Exception, Path, batch_manager.py execute_batch(payload) -- the batch counterpart to… (+18 more)

### Community 8 - "File Manager"
Cohesion: 0.15
Nodes (9): FileManager, FileUploadError, Any, Exception, Path, file_manager.py File-upload wrapper alongside the text-interaction path in…, Module-level convenience wrapper, mirrors execute() being the one-liner entry…, Raised on upload/list/retrieve/delete failures, or an unsupported backend/path. (+1 more)

### Community 9 - "CPA Scaffold CLI"
Cohesion: 0.23
Nodes (20): Namespace, cmd_new(), _copy_reference_skeleton(), _copy_sample_config(), _install_accelerators(), main(), Path, cli.py `cpa new --project-name <name> [--venv|--no-venv]` -- plain argparse +… (+12 more)

### Community 10 - "Environment Resolution"
Cohesion: 0.14
Nodes (17): Any, Path, files.py Thin project-level wrapper over orchestration_accelerator.file,…, upload_file(), test_upload_file_agent_sdk_returns_local_path(), test_upload_file_resolves_environment(), _ensure_dotenv_loaded(), Path (+9 more)

### Community 11 - "Batch Test Fakes"
Cohesion: 0.16
Nodes (8): _FakeBatch, _FakeBatches, _FakeMessage, _FakeResult, _FakeResultEntry, _FakeTextBlock, _install_fake_anthropic(), test_execute_batch_classifies_each_input()

### Community 12 - "Prompt Files + Deps"
Cohesion: 0.13
Nodes (17): Classify Prompt (scaffold_data), Classify SOA (Respond) Prompt (scaffold_data), Escalation Decision Prompt (scaffold_data), Extract v2 Prompt (scaffold_data), Ticket Triage Prompt (scaffold_data), {{<stepName>_output}} Inter-step Threading Convention, Classify Prompt, Classify SOA (Respond) Prompt (+9 more)

### Community 13 - "Guardrails Engine"
Cohesion: 0.21
Nodes (15): Guardrail, _build_rate_limit_guardrail(), _build_redaction_guardrail(), get_guardrail(), load_guardrails(), Any, Exception, Path (+7 more)

### Community 14 - "Scaffold Sync Checker"
Cohesion: 0.26
Nodes (13): check_capability_registry_structure(), check_capability_rule_doc_matches_registry(), check_exact_pairs(), check_examples_referenced(), check_guardrails_yaml_exists(), check_howto_capability_table_matches_registry(), _extract_doc_allowed_lists(), _load_yaml() (+5 more)

### Community 15 - "Context Mgmt: Assistant Prompt Threading"
Cohesion: 0.17
Nodes (11): assistant_prompt prompt field, ClaudeSDKClient, core.py step loop, execute_with_fallback(), FallbackChainExhaustedError, mirror_error system message, Part C: assistant_prompt seed turn, prompt_manager.py (+3 more)

### Community 16 - "Capability Passthrough Concepts"
Cohesion: 0.29
Nodes (8): cache_control capability (messages_api-only), call_messages_api(), dummyDemoSkill (referenced skill), dummyDemoSkill SKILL.md, escalate step, skills step key, templatingDemo process, triage step

### Community 17 - "Capability Registry Schema"
Cohesion: 0.22
Nodes (9): config/capability_registry.yaml (concept), capability_registry.yaml schema, context_mode process key, InMemorySessionStore, SDK SessionStore interface, session_store process key, trimming process key, UnsupportedCapabilityError (+1 more)

### Community 18 - "MCP Scope Config"
Cohesion: 0.29
Nodes (7): allowed_tools step key, .env config, execute(payload) entry point, config/process_registry.yaml (concept), mcp-scope.md rule doc, .mcp.json, mcp_servers step key

### Community 19 - "Guardrails Registry Schema"
Cohesion: 0.29
Nodes (5): guardrails-registry.md rule doc, GUARDRAIL_TYPES, orchestration_accelerator/guardrails.py, config/guardrails.yaml schema, redactPII guardrail

### Community 20 - "MCP Scope Hook"
Cohesion: 0.29
Nodes (6): make_mcp_scope_hook(), _parse_mcp_tool_name(), Any, mcp_scope.py Enforces a process_registry.yaml step's optional `mcp_servers`/…, Returns (server, tool) for a `mcp__<server>__<tool>` name, or None for a non-…, Builds a PreToolUse hook denying MCP tool calls outside the given scope. Non-…

### Community 21 - "Scaffold Sync Tests"
Cohesion: 0.29
Nodes (6): parametrize, Path, test_scaffold_sync.py process_registry.yaml/batch_registry.yaml/rule docs exist…, Covers everything test_root_and_scaffold_copy_match's exact pairs don't:…, test_check_scaffold_sync_script_passes(), test_root_and_scaffold_copy_match()

### Community 22 - "Context Mgmt: Observability/Streaming Plan"
Cohesion: 0.40
Nodes (6): model_router_accelerator/backends.py, execute() structured return shape (breaking change), Part B: model-call observability, Part D: streaming (stream: true), stream step key, TraceRecord dataclass (schema.py)

### Community 23 - "Auth + Guardrail Helpers"
Cohesion: 0.33
Nodes (4): call_agent_sdk(), orchestration_accelerator.guardrails.get_guardrail(), guardrails step key, UnknownGuardrailError

### Community 24 - "Onboarding Prompt Files"
Cohesion: 0.33
Nodes (6): Finalize Prompt (scaffold_data), Verify KYC Prompt (scaffold_data), Welcome Prompt (scaffold_data), Finalize Prompt, Verify KYC Prompt, Welcome Prompt

### Community 25 - "Scaffold Sync Docs"
Cohesion: 0.50
Nodes (3): check_scaffold_sync.py, Keeping the scaffold in sync (rationale), install-git-hooks.sh

### Community 26 - "MCP Server Config"
Cohesion: 0.50
Nodes (3): uvx, mcp-server-git, git

### Community 27 - "Scaffold MCP Config"
Cohesion: 0.50
Nodes (3): uvx, mcp-server-git, git

### Community 28 - "Accelerator Packages"
Cohesion: 1.00
Nodes (3): claude-model-router-accelerator, claude-orchestration-accelerator, claude-project-accelerator

## Ambiguous Edges - Review These
- `Classify Prompt` → `Root requirements.txt`  [AMBIGUOUS]
  requirements.txt · relation: conceptually_related_to

## Knowledge Gaps
- **58 isolated node(s):** `log_pre_tool_use.sh script`, `remind_doc_sync.sh script`, `uvx`, `mcp-server-git`, `install-git-hooks.sh script` (+53 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Classify Prompt` and `Root requirements.txt`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `friendly_error()` connect `Process Registry Core` to `Model Router Backends`, `Prompt Manager`, `Execute Core + Logging`?**
  _High betweenness centrality (0.063) - this node is a cross-community bridge._
- **Why does `call_agent_sdk()` connect `Model Router Backends` to `Process Registry Core`, `MCP Scope Hook`, `Guardrails Engine`, `Execute Core + Logging`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Why does `PromptManager` connect `Prompt Manager` to `Process Registry Core`, `Execute Core + Logging`, `Batch Processing`?**
  _High betweenness centrality (0.048) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `PromptManager` (e.g. with `main()` and `_execute_async()`) actually correct?**
  _`PromptManager` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `execute()` (e.g. with `main()` and `main()`) actually correct?**
  _`execute()` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `get_process()` (e.g. with `main()` and `_resolve_step_configs()`) actually correct?**
  _`get_process()` has 5 INFERRED edges - model-reasoned connections that need verification._