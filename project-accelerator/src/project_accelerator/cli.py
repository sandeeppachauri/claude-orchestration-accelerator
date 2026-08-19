"""
cli.py

`cpa new --project-name <name> [--venv|--no-venv]` -- plain argparse +
venv/subprocess, no templating engine. Generates a starter project and
fully automates installing all four accelerators into the chosen
environment.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # .../claude-orchestration-accelerator
ACCELERATORS_ROOT = REPO_ROOT.parent / "Accelerators"

SKELETON_ENTRIES = [
    "CLAUDE.md",
    "CLAUDE.local.md",
    ".claude",
]


def _copy_reference_skeleton(dest: Path) -> None:
    """One-time snapshot copy of the repo root's reference Claude Code
    project skeleton -- not a live link. A scaffolded project owns its
    own copy and can diverge afterward."""
    for entry in SKELETON_ENTRIES:
        src = REPO_ROOT / entry
        if not src.exists():
            continue
        target = dest / entry
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)


def _copy_sample_config(dest: Path) -> None:
    shutil.copy2(REPO_ROOT / "process_registry.yaml", dest / "process_registry.yaml")
    prompts_dest = dest / "prompts"
    prompts_dest.mkdir(exist_ok=True)
    for prompt_file in (REPO_ROOT / "prompts").glob("*.yaml"):
        shutil.copy2(prompt_file, prompts_dest / prompt_file.name)


def _write_env_file(dest: Path) -> None:
    (dest / ".env").write_text("ENVIRONMENT=local\nDEFAULT_MODEL=claude-sonnet-5\n")


def _write_logger_config(dest: Path) -> None:
    from orchestration_accelerator.logging import DEFAULT_LOGGER_CONFIG_PATH

    shutil.copy2(DEFAULT_LOGGER_CONFIG_PATH, dest / "logger_config.json")


def _write_readme(dest: Path, project_name: str) -> None:
    (dest / "README.md").write_text(
        f"""# {project_name}

Scaffolded by `cpa new --project-name {project_name}` from
`claude-project-accelerator`.

## Run

```python
from project_accelerator import execute

result = execute({{
    "process": "ticketClassification",
    "input": "some ticket text",
    "backend": "agent_sdk",
}})
```

`process_registry.yaml` is the single source of truth for step order and
per-step `{{prompt, model, fallback}}` configuration. `.env` carries
`ENVIRONMENT` and `DEFAULT_MODEL`.

## Tests

```bash
pytest tests/test_sample_pipeline.py
```
"""
    )


def _write_pipeline_runner(dest: Path) -> None:
    pipeline_dir = dest / "pipeline"
    pipeline_dir.mkdir(exist_ok=True)
    (pipeline_dir / "__init__.py").write_text("")
    (pipeline_dir / "run_pipeline.py").write_text(
        '''"""
run_pipeline.py

Reads the step list and per-step config from process_registry.yaml --
nothing here is a hardcoded tuple or dict. Run: python pipeline/run_pipeline.py
"""

import sys

from orchestration_accelerator.registry import get_process
from project_accelerator import execute


def run(process_name: str, input_text: str, backend: str = "agent_sdk") -> dict:
    """Runs every step of `process_name` in the order process_registry.yaml
    defines, by simply not passing payload["step"] -- execute() reads the
    step order from the registry itself."""
    return execute({
        "process": process_name,
        "input": input_text,
        "backend": backend,
    })


def main() -> None:
    process_name = sys.argv[1] if len(sys.argv) > 1 else "ticketClassification"
    input_text = sys.argv[2] if len(sys.argv) > 2 else "Sample input text."

    process = get_process(process_name)
    print(f"Running process '{process_name}' -- steps: {process['steps']}")

    result = run(process_name, input_text)
    for step_name, output in result.items():
        print(f"[{step_name}] -> {output!r}")


if __name__ == "__main__":
    main()
'''
    )


def _write_sample_test(dest: Path) -> None:
    tests_dir = dest / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_sample_pipeline.py").write_text(
        '''"""
test_sample_pipeline.py

Exercises execute() against the shipped ticketClassification sample and
asserts the output satisfies PromptManager.validate_output()'s format
contract. Replaces prompt-description-demo's role as the "does this
actually work end to end" check -- see Master_Accelerator_Plan.md
Section 4.3.

Requires ANTHROPIC_API_KEY (or an ambient OAuth/OS session) to make a
real model call. If no credential is available, the test is skipped
rather than failing -- this file is runnable immediately after scaffold
without requiring credentials, but does not fabricate a passing result.
"""

import pytest

from orchestration_accelerator.prompting import PromptManager
from project_accelerator import execute


def _has_credential() -> bool:
    try:
        from auth_accelerator import resolve_auth

        resolve_auth("local")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _has_credential(), reason="no Claude credential available")
def test_ticket_classification_classify_step():
    result = execute({
        "process": "ticketClassification",
        "step": "classify",
        "input": "I was charged twice for my subscription this month.",
        "backend": "agent_sdk",
    })

    assert "classify" in result
    category = result["classify"]

    pm = PromptManager()
    cfg = pm.get("classify", filename="classify.yaml")
    # Re-validating here proves the returned value already satisfies the
    # format contract -- execute() validates internally too.
    assert pm.validate_output("classify", cfg, category) == category
'''
    )


def _install_accelerators(python_exe: str, accelerators_root: Path) -> list[str]:
    """Installs each accelerator package into python_exe. Returns the list of
    package paths that were missing (skipped) rather than installed."""
    packages = [
        str(accelerators_root / "claude-auth-accelerator"),
        str(accelerators_root / "ClaudeSDKLoggerAccelerator"),
        str(REPO_ROOT),
        str(REPO_ROOT / "model-router"),
    ]
    missing = []
    for package_path in packages:
        if not Path(package_path).exists():
            missing.append(package_path)
            continue
        subprocess.run(
            [python_exe, "-m", "pip", "install", "-e", package_path, "--quiet"],
            check=True,
        )
    return missing


def cmd_new(args: argparse.Namespace) -> None:
    if not args.project_name:
        print("Error: --project-name is required.", file=sys.stderr)
        sys.exit(1)

    if args.python and args.venv:
        print("Error: --python cannot be combined with --venv.", file=sys.stderr)
        sys.exit(1)

    base = Path(args.path).expanduser().resolve() if args.path else Path.cwd()
    base.mkdir(parents=True, exist_ok=True)
    dest = base / args.project_name
    dest.mkdir(parents=True, exist_ok=True)

    _copy_reference_skeleton(dest)
    _copy_sample_config(dest)
    _write_env_file(dest)
    _write_logger_config(dest)
    _write_readme(dest, args.project_name)
    _write_pipeline_runner(dest)
    _write_sample_test(dest)

    if args.python:
        python_exe = str(Path(args.python).expanduser().resolve())
        if not Path(python_exe).exists():
            print(f"Error: --python interpreter not found: {python_exe}", file=sys.stderr)
            sys.exit(1)
        print(f"Using existing interpreter at {python_exe}")
    elif args.venv:
        venv_dir = dest / ".venv"
        venv.create(venv_dir, with_pip=True)
        python_exe = str(
            venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / (
                "python.exe" if sys.platform == "win32" else "python"
            )
        )
        print(f"Created virtual environment at {venv_dir}")
    else:
        python_exe = sys.executable

    accelerators_root = (
        Path(args.accelerators_path).expanduser().resolve()
        if args.accelerators_path
        else ACCELERATORS_ROOT
    )
    print("Installing accelerator packages...")
    missing = _install_accelerators(python_exe, accelerators_root)
    if missing:
        print(
            "\nWarning: the following accelerator packages were NOT installed "
            "(source not found):",
            file=sys.stderr,
        )
        for package_path in missing:
            print(f"  - {package_path}", file=sys.stderr)
        print(
            f"Pass --accelerators-path to point at the '{accelerators_root.name}' "
            "sibling repo, or clone it alongside this repo.",
            file=sys.stderr,
        )
        if not args.allow_missing_accelerators:
            print("Aborting (pass --allow-missing-accelerators to scaffold anyway).", file=sys.stderr)
            sys.exit(1)

    print(f"\nScaffolded project '{args.project_name}' at {dest}")
    print("Created:")
    print("  prompts/*.yaml, process_registry.yaml, .env, logger_config.json")
    print("  pipeline/run_pipeline.py, tests/test_sample_pipeline.py, README.md")
    print("  CLAUDE.md, CLAUDE.local.md, .claude/ (reference skeleton)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="cpa")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="Scaffold a new accelerator-based project")
    new_parser.add_argument("--project-name", required=True, help="Name of the new project")
    new_parser.add_argument(
        "--path",
        help="Parent directory to scaffold into (default: current directory)",
    )
    venv_group = new_parser.add_mutually_exclusive_group()
    venv_group.add_argument(
        "--venv", dest="venv", action="store_true", help="Create a fresh virtual environment"
    )
    venv_group.add_argument(
        "--no-venv",
        dest="venv",
        action="store_false",
        help="Install into the currently active environment",
    )
    new_parser.add_argument(
        "--python",
        help="Path to an existing python interpreter (e.g. an existing venv) to install into; "
        "cannot be combined with --venv",
    )
    new_parser.add_argument(
        "--accelerators-path",
        help="Path to the sibling 'Accelerators' repo containing claude-auth-accelerator and "
        "ClaudeSDKLoggerAccelerator (default: '../Accelerators' next to this repo)",
    )
    new_parser.add_argument(
        "--allow-missing-accelerators",
        action="store_true",
        help="Scaffold even if claude-auth-accelerator/ClaudeSDKLoggerAccelerator can't be found",
    )
    new_parser.set_defaults(venv=True, func=cmd_new)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
