"""
cli.py

`cpa new --project-name <name> [--venv|--no-venv]` -- plain argparse +
venv/subprocess, no templating engine. Generates a starter project and
fully automates installing all four accelerators into the chosen
environment.
"""

from __future__ import annotations

import argparse
import importlib.resources
import shutil
import subprocess
import sys
import venv
from pathlib import Path

# Local-checkout convenience only: when this repo (and its sibling
# Accelerators repo) are cloned on disk, _install_accelerators() prefers
# editable installs from these paths over fetching from git. Neither path
# needs to exist -- `cpa` works standalone via pip/pipx from git alone,
# since the scaffold template itself ships as package data (scaffold_data/)
# rather than being read from REPO_ROOT.
REPO_ROOT = Path(__file__).resolve().parents[3]
ACCELERATORS_ROOT = REPO_ROOT.parent / "Accelerators"

ORCHESTRATION_GIT_URL = "https://github.com/sandeeppachauri/claude-orchestration-accelerator.git"
ACCELERATORS_GIT_URL = "https://github.com/sandeeppachauri/Accelerators.git"

SKELETON_ENTRIES = [
    "CLAUDE.md",
    "CLAUDE.local.md",
    ".claude",
]


def _scaffold_data_dir() -> Path:
    return Path(str(importlib.resources.files("project_accelerator") / "scaffold_data"))


def _copy_reference_skeleton(dest: Path) -> None:
    """One-time snapshot copy of the packaged reference Claude Code project
    skeleton -- not a live link. A scaffolded project owns its own copy and
    can diverge afterward."""
    data_dir = _scaffold_data_dir()
    for entry in SKELETON_ENTRIES:
        src = data_dir / entry
        if not src.exists():
            continue
        target = dest / entry
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            shutil.copy2(src, target)


def _copy_sample_config(dest: Path) -> None:
    data_dir = _scaffold_data_dir()
    shutil.copy2(data_dir / "process_registry.yaml", dest / "process_registry.yaml")
    prompts_dest = dest / "prompts"
    prompts_dest.mkdir(exist_ok=True)
    for prompt_file in (data_dir / "prompts").glob("*.yaml"):
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


def _install_accelerators(
    python_exe: str, accelerators_root: Path, allow_missing_accelerators: bool
) -> list[str]:
    """Installs each accelerator package into python_exe. Prefers an editable
    install from a local checkout (accelerators_root / REPO_ROOT) when
    present -- convenient for contributors -- and otherwise falls back to
    installing straight from GitHub, so `cpa new` works standalone from a
    pip/pipx install with no repo cloned locally. Returns the list of
    packages that could not be installed either way (only possible for the
    two accelerators_root packages when allow_missing_accelerators is set)."""
    local_packages = [
        accelerators_root / "claude-auth-accelerator",
        accelerators_root / "ClaudeSDKLoggerAccelerator",
    ]
    git_specs = [
        f"git+{ACCELERATORS_GIT_URL}#subdirectory=claude-auth-accelerator",
        f"git+{ACCELERATORS_GIT_URL}#subdirectory=ClaudeSDKLoggerAccelerator",
    ]

    missing = []
    for local_path, git_spec in zip(local_packages, git_specs):
        if local_path.exists():
            subprocess.run(
                [python_exe, "-m", "pip", "install", "-e", str(local_path), "--quiet"],
                check=True,
            )
            continue
        try:
            subprocess.run(
                [python_exe, "-m", "pip", "install", git_spec, "--quiet"],
                check=True,
            )
        except subprocess.CalledProcessError:
            if not allow_missing_accelerators:
                raise
            missing.append(git_spec)

    # This repo's own packages: editable install if cloned locally,
    # otherwise install straight from GitHub.
    if REPO_ROOT.exists() and (REPO_ROOT / "pyproject.toml").exists():
        subprocess.run(
            [python_exe, "-m", "pip", "install", "-e", str(REPO_ROOT), "--quiet"], check=True
        )
        subprocess.run(
            [python_exe, "-m", "pip", "install", "-e", str(REPO_ROOT / "model-router"), "--quiet"],
            check=True,
        )
    else:
        subprocess.run(
            [python_exe, "-m", "pip", "install", f"git+{ORCHESTRATION_GIT_URL}", "--quiet"],
            check=True,
        )
        subprocess.run(
            [
                python_exe,
                "-m",
                "pip",
                "install",
                f"git+{ORCHESTRATION_GIT_URL}#subdirectory=model-router",
                "--quiet",
            ],
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
    try:
        missing = _install_accelerators(python_exe, accelerators_root, args.allow_missing_accelerators)
    except subprocess.CalledProcessError as exc:
        print(f"\nError: failed to install accelerator packages: {exc}", file=sys.stderr)
        print(
            "Pass --accelerators-path to use a local checkout, or "
            "--allow-missing-accelerators to scaffold without them.",
            file=sys.stderr,
        )
        sys.exit(1)
    if missing:
        print(
            "\nWarning: the following accelerator packages could not be installed "
            "(from local checkout or GitHub):",
            file=sys.stderr,
        )
        for spec in missing:
            print(f"  - {spec}", file=sys.stderr)

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
