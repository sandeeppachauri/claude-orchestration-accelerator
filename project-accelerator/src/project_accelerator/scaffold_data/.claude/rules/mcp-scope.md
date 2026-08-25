---
description: Schema guidance for MCP server/tool scoping and the skills step key
paths:
  - "**/config/process_registry.yaml"
---

# MCP server/tool scoping (`mcp_servers` / `allowed_tools`) and `skills`

Two independent, optional `config/process_registry.yaml` step keys that
narrow (never grant) what a step's model call may reach. Neither is a
guardrail -- see `.claude/rules/guardrails-registry.md` for that, unrelated
mechanism.

## `mcp_servers` / `allowed_tools`

MCP server *connections* (`command`/`args`/`url`/`env`) live in the
standard Claude Code `.mcp.json` (project-level) or global Claude
settings -- this accelerator never defines them. `claude_agent_sdk`
already loads MCP servers from there automatically; these two keys only
narrow which of those already-configured servers/tools a given step may
use.

```yaml
classify:
  prompt: classify.yaml
  model: claude-sonnet-5
  fallback: [claude-sonnet-4-6]
  mcp_servers: [git]                     # server names, must match .mcp.json/global config
  allowed_tools: ["mcp__git__log"]       # optional, finer grain
```

- Two independent grains:
  - **server-level** (`mcp_servers`) -- always derivable from `.mcp.json`.
  - **tool-level** (`allowed_tools`) -- finer, opt-in. Tool names follow
    the `mcp__<serverName>__<toolName>` convention but aren't derivable
    from `.mcp.json` alone -- they're only known once a server has been
    connected once (or documented) via the MCP handshake.
- `mcp_servers` absent -> no MCP restriction at all -- any server
  reachable via `.mcp.json`/global settings is usable (**fail-open**).
- `mcp_servers` present, `allowed_tools` absent -> step may use any tool
  on the *listed* servers only, nothing from other configured servers.
- Both present -> step is limited to exactly the named tools (which must
  belong to one of the named servers).
- Enforced by `orchestration_accelerator.mcp_scope.make_mcp_scope_hook()`,
  a `PreToolUse` hook attached by `call_agent_sdk()`
  (`model-router/src/model_router_accelerator/backends.py`) whenever a
  step sets either key. Non-MCP tool names always pass through untouched
  -- this hook only ever narrows MCP access, never grants it.
  `ClaudeAgentOptions.mcp_servers` itself is left unset, so the SDK's own
  default `.mcp.json`/global-settings discovery still applies.
- Both keys are whitelisted in `config/capability_registry.yaml`'s
  `agent_sdk.allowed` list -- there is no MCP tool-call concept on the
  `messages_api` backend, so neither key is whitelisted there.
- See `.mcp.json` (repo root) for the shipped `git` MCP server example,
  and `config/process_registry.yaml`'s `templatingDemo.escalate` step for
  the commented-out worked example (`mcp_servers: [git]`,
  `allowed_tools: ["mcp__git__log"]`).

## `skills`

A third, independent, optional step key. Unlike MCP tools, Skills are
**not** named individually as tools -- every skill invocation routes
through one generic `"Skill"` tool call, so `allowed_tools`/`PreToolUse`
can only allow/deny Skills as a whole, not per-skill. Per-skill
restriction instead uses `ClaudeAgentOptions`'s own native
`skills: list[str] | "all" | None` field -- native SDK passthrough, no
hook, same tier as `max_turns`.

```yaml
escalate:
  prompt: escalation_decision.yaml
  model: claude-opus-4-8
  fallback: [claude-sonnet-5]
  skills: [dummyDemoSkill]   # names, passed straight to ClaudeAgentOptions.skills
```

- Omitting `skills` = SDK default (all skills visible/usable, or none,
  per whatever `setting_sources` already governs) -- no accelerator-
  imposed restriction, **fail-open**.
- `agent_sdk` backend: `skills` is a real `ClaudeAgentOptions` field, so
  `call_agent_sdk()` forwards it straight through via `**extra` -- no
  special handling needed.
- `messages_api` backend: the raw Messages API only supports Skills on
  the **beta** client, nested as
  `container.skills: [{skill_id, type, version}]` -- not a flat kwarg.
  `call_messages_api()` (`model-router/src/model_router_accelerator/backends.py`)
  translates a step's flat `skills: [name, ...]` list into that shape
  (defaulting `type` to `"custom"` -- project-managed skills; pass a
  fully-qualified dict instead of a bare name for an Anthropic-hosted
  skill) and switches to `client.beta.messages.create(...)` only when
  `skills` is set. Steps without `skills` keep using the stable, non-beta
  client, unaffected.
- `skills` is whitelisted in `config/capability_registry.yaml` for
  **both** `agent_sdk` and `messages_api` -- the wire shape differs per
  backend, but a step's `skills` value stays the same flat list of names
  either way.
- See `.claude/skills/dummyDemoSkill/SKILL.md` for the shipped dummy
  example skill, and `config/process_registry.yaml`'s
  `templatingDemo.escalate` step for the commented-out worked example.
