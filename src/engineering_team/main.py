#!/usr/bin/env python
"""Dynamic CLI entrypoint for AutoDev Crew / EngineeringTeam.

AutoDev Crew adds an automated validation quality gate after project generation:
- dynamic requirements remain supported,
- Gradio remains the only generated frontend target,
- CrewAI agents use OpenAI through `openai/gpt-4o`,
- generated Python files are syntax-checked,
- generated unit tests are executed,
- stdout/stderr are captured,
- a limited GPT-4o repair loop can patch failed generated files,
- validation reports are written into each timestamped output folder.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from engineering_team.crew import EngineeringTeam
from engineering_team.validation import validate_generated_project, validation_summary_to_markdown
from engineering_team.deployment import generate_deployment_assets, create_run_zip
from engineering_team.observability import write_observability_artifacts

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")

DEFAULT_REQUIREMENTS = """
Build a simple account management system for a trading simulation platform.
The system should allow users to create an account, deposit funds, withdraw funds,
buy shares, sell shares, report holdings, report portfolio value, report profit/loss,
and list transaction history. The system must prevent invalid withdrawals, purchases,
and sales. Include a deterministic get_share_price(symbol) test function for AAPL,
TSLA, and GOOGL.
""".strip()


def slugify(value: str) -> str:
    """Convert a project name into a safe folder-friendly slug."""
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "autodev_project"


def normalize_module_name(module_name: str) -> tuple[str, str]:
    """Return (module_file, module_import) from user-provided module name."""
    module_name = module_name.strip().replace("-", "_")
    if not module_name:
        module_name = "generated_app"

    if module_name.endswith(".py"):
        module_import = module_name[:-3]
        module_file = module_name
    else:
        module_import = module_name
        module_file = f"{module_name}.py"

    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", module_import):
        raise ValueError(
            "module_name must be a valid Python module name, for example: accounts or accounts.py"
        )

    return module_file, module_import


def normalize_class_name(class_name: str) -> str:
    """Validate and return a safe Python class name."""
    class_name = class_name.strip()
    if not re.match(r"^[A-Z][A-Za-z0-9_]*$", class_name):
        raise ValueError(
            "class_name must be a valid Python class name in PascalCase, for example: Account"
        )
    return class_name


def read_requirements(args: argparse.Namespace) -> str:
    """Read requirements from --requirements, --requirements-file, interactive prompt, or default demo."""
    if getattr(args, "requirements_file", None):
        path = Path(args.requirements_file)
        if not path.exists():
            raise FileNotFoundError(f"Requirements file not found: {path}")
        return path.read_text(encoding="utf-8").strip()

    if getattr(args, "requirements", None):
        return args.requirements.strip()

    if getattr(args, "interactive", False):
        print("Enter your software requirements. Press Ctrl+D / Ctrl+Z when finished:\n")
        entered = sys.stdin.read().strip()
        if entered:
            return entered

    return DEFAULT_REQUIREMENTS


def build_inputs(args: argparse.Namespace) -> Dict[str, Any]:
    """Build the CrewAI kickoff input dictionary and create a traceable run folder."""
    project_name = args.project_name.strip() if args.project_name else "AutoDev Generated Project"
    project_slug = slugify(project_name)
    module_file, module_import = normalize_module_name(args.module_name or "generated_app")
    class_name = normalize_class_name(args.class_name or "GeneratedApp")
    requirements = read_requirements(args)
    frontend_framework = "Gradio"  # AutoDev Crew intentionally supports Gradio only.

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{timestamp}_{project_slug}"
    output_root = Path(args.output_root or "output")
    run_output_dir = output_root / run_id
    run_output_dir.mkdir(parents=True, exist_ok=True)

    inputs: Dict[str, Any] = {
        "project_name": project_name,
        "project_slug": project_slug,
        "requirements": requirements,
        "module_file": module_file,
        "module_import": module_import,
        "module_name": module_file,  # Backward-compatible alias for older prompts.
        "class_name": class_name,
        "frontend_framework": frontend_framework,
        "app_file": "app.py",
        "test_file": f"test_{module_import}.py",
        "run_id": run_id,
        "run_output_dir": str(run_output_dir).replace("\\", "/"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "workflow_version": "1.1.0",
        "llm_provider": "OpenAI",
        "llm_model": "openai/gpt-4o",
        "repair_model": "gpt-4o",
        "agent_count": 9,
        "task_count": 9,
        "deployment_assets_enabled": True,
        "dashboard_enabled": True,
        "dashboard_framework": "Gradio",
        "validation_enabled": True,
        "validation_report_file": "06_validation_report.md",
        "validation_json_file": "validation_report.json",
    }

    manifest_path = run_output_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(inputs, indent=2), encoding="utf-8")
    return inputs


def update_manifest(inputs: Dict[str, Any], updates: Dict[str, Any]) -> None:
    """Merge updates into run_manifest.json."""
    inputs.update(updates)
    manifest_path = Path(inputs["run_output_dir"]) / "run_manifest.json"
    manifest_path.write_text(json.dumps(inputs, indent=2), encoding="utf-8")


def kickoff_autodev(inputs: Dict[str, Any]) -> Any:
    """Run the EngineeringTeam crew with prebuilt inputs."""
    return EngineeringTeam().crew().kickoff(inputs=inputs)


def run_autodev_pipeline(
    inputs: Dict[str, Any],
    *,
    run_validation: bool = True,
    run_tests: bool = True,
    repair_attempts: int = 1,
) -> Dict[str, Any]:
    """Run generation plus the local validation quality gate."""
    crew_result = kickoff_autodev(inputs)
    validation_summary = None

    if run_validation:
        validation_summary = validate_generated_project(
            inputs,
            repair_attempts=repair_attempts,
            run_tests=run_tests,
        )
        update_manifest(
            inputs,
            {
                "validation_overall_passed": validation_summary.overall_passed,
                "validation_completed_at": validation_summary.completed_at,
                "repair_attempts_used": validation_summary.repair_attempts_used,
                "repair_attempts_requested": repair_attempts,
                "tests_executed": run_tests,
            },
        )
    else:
        update_manifest(
            inputs,
            {
                "validation_overall_passed": None,
                "validation_completed_at": None,
                "repair_attempts_used": 0,
                "repair_attempts_requested": repair_attempts,
                "tests_executed": False,
                "validation_note": "Validation skipped by user.",
            },
        )

    deployment_summary = generate_deployment_assets(inputs)
    update_manifest(inputs, deployment_summary)

    observability_summary = write_observability_artifacts(inputs)
    update_manifest(inputs, observability_summary)

    final_zip = create_run_zip(Path(inputs["run_output_dir"]))
    update_manifest(inputs, {"download_zip": str(final_zip)})

    return {
        "crew_result": crew_result,
        "validation_summary": validation_summary,
        "deployment_summary": deployment_summary,
        "observability_summary": observability_summary,
        "inputs": inputs,
    }


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run AutoDev Crew: a dynamic CrewAI engineering team with validation and production deployment assets."
    )
    parser.add_argument(
        "--project-name",
        default="AutoDev Generated Project",
        help="Human-readable project name. Used for output folder naming and prompts.",
    )
    parser.add_argument(
        "--requirements",
        help="Inline natural-language software requirements.",
    )
    parser.add_argument(
        "--requirements-file",
        help="Path to a text/markdown file containing the requirements.",
    )
    parser.add_argument(
        "--module-name",
        default="generated_app",
        help="Backend Python module name, for example accounts or accounts.py.",
    )
    parser.add_argument(
        "--class-name",
        default="GeneratedApp",
        help="Primary backend class name, for example Account or TaskManager.",
    )
    parser.add_argument(
        "--frontend-framework",
        default="Gradio",
        help="Frontend target for the prototype. This product supports Gradio only; this value is retained for compatibility.",
    )
    parser.add_argument(
        "--output-root",
        default="output",
        help="Root directory where timestamped generated project folders are created.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Read requirements interactively from stdin.",
    )
    parser.add_argument(
        "--repair-attempts",
        type=int,
        default=3,
        help="Number of GPT-4o repair attempts after failed validation. Use 0 to disable repair; 2-3 is recommended for complex apps.",
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip syntax checks, unit test execution, and repair loop.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Run syntax checks but skip generated unit test execution.",
    )
    return parser.parse_args(argv)


def run(argv: Optional[list[str]] = None) -> Any:
    """Run the dynamic engineering crew from the command line."""
    load_dotenv()
    args = parse_args(argv)
    inputs = build_inputs(args)

    print("\n🚀 AutoDev Crew run initialized")
    print(f"Project: {inputs['project_name']}")
    print(f"Backend: {inputs['module_file']} / class {inputs['class_name']}")
    print("Frontend: Gradio")
    print("LLM: openai/gpt-4o")
    print(f"Output directory: {inputs['run_output_dir']}")
    print(f"Validation: {'off' if args.skip_validation else 'on'}")
    print(f"Repair attempts: {args.repair_attempts}")
    print("Deployment assets: on\n")

    result = run_autodev_pipeline(
        inputs,
        run_validation=not args.skip_validation,
        run_tests=not args.skip_tests,
        repair_attempts=max(0, args.repair_attempts),
    )

    print("\n✅ AutoDev Crew generation completed")
    validation_summary = result.get("validation_summary")
    if validation_summary:
        print(validation_summary_to_markdown(validation_summary))
    else:
        print("Validation skipped.")
    print(f"\nGenerated files are available in: {inputs['run_output_dir']}")
    deployment_summary = result.get("deployment_summary") or {}
    if deployment_summary.get("download_zip"):
        print(f"Download package: {deployment_summary['download_zip']}")
    print()
    return result


def train() -> None:
    """Placeholder for CrewAI training command compatibility."""
    print("Training is not configured in AutoDev Crew. Use `crewai train` only after adding training settings.")


def replay() -> None:
    """Placeholder for CrewAI replay command compatibility."""
    print("Replay is not configured in AutoDev Crew. Use CrewAI replay after adding a saved task id workflow.")


def test() -> None:
    """Placeholder for CrewAI test command compatibility."""
    print("CrewAI test command is not configured. Generated-project validation and deployment asset generation run after each normal generation.")


if __name__ == "__main__":
    run()
