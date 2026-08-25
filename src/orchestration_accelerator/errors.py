"""
errors.py

Every accelerator exception message is meant to be read by two different
audiences at once: a functional/business user (who needs a plain-English
sentence saying what went wrong and what to do about it) and an engineer
debugging it (who needs the exact values involved). friendly_error() joins
both into one message so a single raised exception -- surfaced as-is in a
terminal, a log line, or a support ticket -- serves both readers without
requiring a second lookup.
"""

from __future__ import annotations


def friendly_error(summary: str, technical: str) -> str:
    """summary: one plain-English sentence, no jargon, safe to hand to a
    non-technical reader as-is. technical: the exact identifiers/values a
    developer needs to act (step names, allowed lists, raw exception
    text, file paths, counts, etc). Always returns both, never one or the
    other, so no exception message in this codebase silently favors one
    audience over the other."""
    summary = summary.rstrip()
    if not summary.endswith((".", "!", "?")):
        summary += "."
    return f"{summary} Technical detail: {technical}"
