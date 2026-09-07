FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN apt-get update && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --quiet \
    "git+https://github.com/sandeeppachauri/Accelerators.git#subdirectory=claude-auth-accelerator" \
    "git+https://github.com/sandeeppachauri/Accelerators.git#subdirectory=ClaudeSDKLoggerAccelerator" \
    "claude-agent-sdk" "anthropic" "fastapi" "uvicorn"

# claude-orchestration-accelerator isn't published to PyPI -- install it
# from git in its own step first, so model-router/project-accelerator's
# plain "claude-orchestration-accelerator>=0.1.0" dependency line is
# already satisfied by the time pip resolves it, instead of pip trying
# (and failing) to find a PyPI distribution for it.
RUN pip install --no-cache-dir --quiet \
    "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git"
RUN pip install --no-cache-dir --quiet \
    "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git#subdirectory=model-router"
RUN pip install --no-cache-dir --quiet \
    "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git#subdirectory=project-accelerator"

# Non-root user whose home matches claude-auth-accelerator's OS-session
# mount convention (/home/agent/.claude, /home/agent/.claude.json) -- lets
# a host's `claude login` session be bind-mounted in for containerized
# OAuth auth, instead of requiring ANTHROPIC_API_KEY. See docker-compose.yml.
RUN useradd --create-home --home-dir /home/agent --shell /bin/bash agent \
    && chown -R agent:agent /app
USER agent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "examples/api_server.py"]
