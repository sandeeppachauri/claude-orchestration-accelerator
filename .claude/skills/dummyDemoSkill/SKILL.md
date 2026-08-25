---
name: dummyDemoSkill
description: >
  Dummy example skill demonstrating the process_registry.yaml `skills` step
  key (native ClaudeAgentOptions.skills passthrough -- see .claude/rules/
  mcp-scope.md's skills section). Not a real capability -- exists only so
  templatingDemo.escalate's commented-out `skills: [dummyDemoSkill]` example
  has a real, working skill to reference.
---

# dummyDemoSkill

A minimal placeholder skill. When invoked, it just says hello -- it has no
real functionality. It exists purely to demonstrate the shape of
`process_registry.yaml`'s `skills` step key end to end: a project author
opts a step into per-skill restriction by setting `skills: [dummyDemoSkill]`
(or `skills: "all"`), and `ClaudeAgentOptions.skills` filters what the model
can see/invoke to exactly the named skills.

## What it does

Responds with a short, fixed greeting acknowledging it was invoked. Use it
to smoke-test that a step's `skills` restriction is actually wired up
(the model can invoke this skill but not some other, unlisted skill).
