Run a process end to end via `pipeline/run_pipeline.py`.

Ask the user which process (default `ticketClassification`) and what
input text, then run:

```bash
python pipeline/run_pipeline.py <process> "<input text>"
```

Needs a real credential (`ANTHROPIC_API_KEY` or `claude login`) — say so
up front if neither is set.
