#!/usr/bin/env bash
# Quick smoke test: unit tests (no credential needed) then, if a
# credential is available, one real pipeline run.
set -e

pytest tests/test_sample_pipeline.py -q

if [ -n "$ANTHROPIC_API_KEY" ]; then
  python pipeline/run_pipeline.py ticketClassification "sample ticket text"
else
  echo "ANTHROPIC_API_KEY not set -- skipping live pipeline run (unit tests passed)."
fi
