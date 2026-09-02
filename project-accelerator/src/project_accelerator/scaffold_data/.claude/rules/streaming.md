# `stream` / `on_chunk` -- real-time chunk emission

New optional step key `stream: true` in `config/process_registry.yaml`,
capability-passthrough tier (same as `max_turns`/`thinking`) -- whitelisted
per backend in `config/capability_registry.yaml`. Omitted (the default) =
today's fully-buffered behavior, byte-for-byte unchanged: the step's
model call is made, fully accumulated, and only then returned.

```yaml
label:
  prompt: fewshot_seed.yaml
  model: claude-haiku-4-5-20251001
  fallback: [claude-haiku-4-5-20251001]
  stream: true   # capability passthrough -- emits chunks as they arrive
```

## `execute()`'s `on_chunk` callback

`execute()`'s payload gains an optional `on_chunk` callback (sync or
async callable, `(step_name: str, chunk: str) -> None`). When a step has
`stream: true` **and** the caller supplied `on_chunk`, `core.py` invokes
it once per chunk as the backend call yields them. When a step has
`stream: true` but the caller supplied no `on_chunk`, chunks are simply
accumulated (same end result as non-streaming, minus the real-time
emission) -- `stream: true` with no callback never raises, since a
caller might enable it only for some steps or add the callback later.

```python
def print_chunk(step_name: str, chunk: str) -> None:
    print(chunk, end="", flush=True)

result = execute({
    "process": "fewshotLabeling",
    "step": "label",
    "input": {"ticket_text": "..."},
    "backend": "messages_api",
    "on_chunk": print_chunk,
})
```

## Cross-step wiring stays simple

Step 2 always waits for step 1's stream to fully complete before
starting, and receives the same complete assembled text via
`{{step1_output}}` as today -- streaming is purely an emission/
observability channel to the caller, not a new data shape flowing
between steps. `results[step_name]["output"]` is identical whether or
not `stream: true` was set. This keeps streaming fully orthogonal to the
`{{<stepName>_output}}` threading mechanism (see
`.claude/rules/process-registry.md`) -- no change needed there.

## Backend mechanics

- **`agent_sdk`**: `stream: true` sets
  `ClaudeAgentOptions.include_partial_messages = True` under the hood.
  Both `query()` (used by `context_mode: threaded` steps) and
  `ClaudeSDKClient` (used by `context_mode: session` steps) then yield
  `StreamEvent` messages (`{uuid, session_id, event: dict,
  parent_tool_use_id}`, where `event` is the raw Anthropic API stream
  event) interleaved with the normal `AssistantMessage`/`ResultMessage`
  stream. `call_agent_sdk()`/`run_session_turn()` filter for
  `event["delta"]["type"] == "text_delta"` and invoke `on_chunk` per
  delta, while still accumulating the final concatenated text from
  completed messages for `results[step]["output"]`, unchanged.

  **Note for whoever touches this next**: the public SDK doc page
  (`code.claude.com/docs/en/agent-sdk/python`) states `query()` "does
  not return granular text chunk events" -- this is stale/wrong against
  the SDK's actual `types.py` source, which has
  `include_partial_messages`/`StreamEvent`. Trust the installed
  package's source, re-verify against it on every SDK version bump
  rather than the doc page.
- **`messages_api`**: `stream: true` switches from a single blocking
  `client.messages.create()` call to `client.messages.stream(...)`
  (a context manager) -- iterate the stream, filter for
  `event.type == "content_block_delta" and event.delta.type ==
  "text_delta"`, invoke `on_chunk` per delta, and call
  `message_stream.get_final_message()` afterward for the same
  usage/stop_reason/etc. capture Part B's observability work already
  does. Incompatible with the `skills` capability's beta-client
  container mode in this accelerator (not attempted) -- only the
  stable, non-beta client streams.
- This mechanism is identical for `context_mode: "threaded"` and
  `context_mode: "session"` steps on `agent_sdk`, since
  `include_partial_messages` is a `ClaudeAgentOptions` field either way
  -- streaming is fully orthogonal to `context_mode` (see
  `.claude/rules/context-mode.md`).

See `config/process_registry.yaml`'s `streamingDemo.narrate` step +
`examples/run_streaming.py` for a worked example.
