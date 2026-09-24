FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN apt-get update && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

# claude-auth-accelerator arrives transitively through model-router's own
# pinned dependency -- do not list it here separately with a different URL
# spelling, or pip sees two specs for one package name and fails to
# resolve. ClaudeSDKLoggerAccelerator has no PyPI distribution and isn't a
# transitive dependency of anything above, so it's still installed
# explicitly, pinned to a commit SHA (the Accelerators repo has no tags).
# claude-orchestration-accelerator/model-router are pinned to release tag
# 0.2.1 -- see project-accelerator/src/project_accelerator/cli.py's
# ORCHESTRATION_GIT_PIN / ACCELERATORS_GIT_PIN for why and where to bump
# these together on the next release.
RUN pip install --no-cache-dir --quiet \
    "git+https://github.com/sandeeppachauri/claude-orchestration-accelerator.git@0.2.1#subdirectory=project-accelerator" \
    "git+https://github.com/sandeeppachauri/Accelerators.git@66436dff3b87186c13f2ff4a77b091808517fe93#subdirectory=ClaudeSDKLoggerAccelerator" \
    "claude-agent-sdk" "anthropic" "fastapi" "uvicorn" \
    && pip check

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
