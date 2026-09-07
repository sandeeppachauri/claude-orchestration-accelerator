FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir --quiet \
    "git+https://github.com/sandeeppachauri/Accelerators.git#subdirectory=claude-auth-accelerator" \
    "git+https://github.com/sandeeppachauri/Accelerators.git#subdirectory=ClaudeSDKLoggerAccelerator" \
    -e . \
    -e ./model-router \
    -e ./project-accelerator \
    "claude-agent-sdk" "anthropic" "fastapi" "uvicorn"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "examples/api_server.py"]
