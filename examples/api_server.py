"""
api_server.py

FastAPI wrapper around execute() -- a live reference for the
`--docker-project yes` cpa scaffold flag (see project-accelerator/README.md
and .claude/rules/... for the flag itself). Demonstrates deploying this
repo's own ticketClassification process behind an HTTP API, buildable via
the root Dockerfile/docker-compose.yml.

GET  /health    -- liveness check, no model call (used by the container's
                   HEALTHCHECK).
POST /classify  -- runs config/process_registry.yaml's `ticketClassification`
                   process.

Needs a credential (ANTHROPIC_API_KEY env var, or an ambient `claude
login` OAuth session) resolved via claude-auth-accelerator for /classify;
/health needs none.

Run directly (from repo root): python examples/api_server.py
Or via Docker: docker compose up --build

Sample request:
    curl -X POST http://localhost:8000/classify \\
      -H "Content-Type: application/json" \\
      -d '{"input": "my printer is broken"}'
"""

from __future__ import annotations

from auth_accelerator.exceptions import AuthResolutionError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from project_accelerator import execute

app = FastAPI(title="claude-orchestration-accelerator example API")


class ClassifyRequest(BaseModel):
    input: str
    environment: str | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"input": "my printer is broken"},
                {"input": "I was double charged for my subscription", "environment": "local"},
            ]
        }
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/classify")
def classify(request: ClassifyRequest) -> dict:
    payload = {
        "process": "ticketClassification",
        "step": "classify",
        "input": request.input,
        "backend": "agent_sdk",
    }
    if request.environment:
        payload["environment"] = request.environment

    try:
        result = execute(payload)
    except AuthResolutionError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"No credential resolved ({exc}). Set ANTHROPIC_API_KEY or run `claude login`.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"execute() failed -- is 'ticketClassification' defined in "
            f"config/process_registry.yaml? ({exc})",
        )

    return result["classify"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
