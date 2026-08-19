#!/usr/bin/env bash
# Minimal illustrative sample hook script referenced from .claude/settings.json's
# "hooks" key. This is NOT the real logging wrapper -- the real wrapper lives in
# Python at orchestration_accelerator/logging/ and is wired via
# sdk_logger_accelerator's pre_tool_use_hook/post_tool_use_hook. This script only
# demonstrates that a hooks entry in settings.json can point at a plain shell
# script file living under .claude/hooks/.
echo "[PreToolUse] a tool is about to run" >&2
