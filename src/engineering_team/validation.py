"""Validation and repair utilities for AutoDev Crew.

AutoDev Crew includes a deterministic quality gate after the CrewAI generation step:
- clean common markdown fence artifacts from generated Python files,
- compile generated Python files,
- run generated unit tests,
- capture stdout/stderr/logs,
- optionally perform a limited GPT-4o repair loop,
- write machine-readable and human-readable validation reports.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


PYTHON_FENCE_RE = re.compile(r"^\s*```(?:python|py)?\s*\n(?P<code>.*?)(?:\n```\s*)$", re.DOTALL | re.IGNORECASE)
GENERIC_FENCE_RE = re.compile(r"^\s*```\s*\n(?P<code>.*?)(?:\n```\s*)$", re.DOTALL)


@dataclass
class CheckResult:
    """Result for one validation check."""

    name: str
    passed: bool
    details: str = ""
    log_file: Optional[str] = None


@dataclass
class ValidationSummary:
    """Structured validation output."""

    run_id: str
    run_output_dir: str
    started_at: str
    completed_at: str = ""
    overall_passed: bool = False
    repair_attempts_requested: int = 0
    repair_attempts_used: int = 0
    checks: List[CheckResult] = field(default_factory=list)
    generated_files: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_output_dir": self.run_output_dir,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "overall_passed": self.overall_passed,
            "repair_attempts_requested": self.repair_attempts_requested,
            "repair_attempts_used": self.repair_attempts_used,
            "checks": [check.__dict__ for check in self.checks],
            "generated_files": self.generated_files,
        }


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_markdown_fence(content: str) -> Tuple[str, bool]:
    """Remove a wrapping markdown code fence when the whole file is fenced."""
    match = PYTHON_FENCE_RE.match(content) or GENERIC_FENCE_RE.match(content)
    if not match:
        return content, False
    return match.group("code").strip() + "\n", True


def clean_generated_python_files(run_dir: Path, python_files: Iterable[str]) -> CheckResult:
    """Clean generated Python files that accidentally include markdown fences."""
    cleaned: List[str] = []
    missing: List[str] = []
    errors: List[str] = []

    for relative_name in python_files:
        path = run_dir / relative_name
        if not path.exists():
            missing.append(relative_name)
            continue
        try:
            original = _read_text(path)
            cleaned_content, changed = _strip_markdown_fence(original)
            if changed:
                _write_text(path, cleaned_content)
                cleaned.append(relative_name)
        except Exception as exc:  # noqa: BLE001 - validation should report all errors.
            errors.append(f"{relative_name}: {type(exc).__name__}: {exc}")

    details_parts = []
    if cleaned:
        details_parts.append("Cleaned markdown fences from: " + ", ".join(cleaned))
    if missing:
        details_parts.append("Missing Python files: " + ", ".join(missing))
    if errors:
        details_parts.append("Errors: " + "; ".join(errors))
    if not details_parts:
        details_parts.append("No markdown fence cleanup required.")

    return CheckResult(
        name="python_file_cleanup",
        passed=not errors,
        details="\n".join(details_parts),
    )


def compile_python_files(run_dir: Path, python_files: Iterable[str]) -> List[CheckResult]:
    """Compile generated Python files using ast.parse for clear syntax feedback."""
    results: List[CheckResult] = []
    for relative_name in python_files:
        path = run_dir / relative_name
        if not path.exists():
            results.append(
                CheckResult(
                    name=f"compile:{relative_name}",
                    passed=False,
                    details=f"File not found: {relative_name}",
                )
            )
            continue
        try:
            ast.parse(_read_text(path), filename=str(path))
            results.append(
                CheckResult(
                    name=f"compile:{relative_name}",
                    passed=True,
                    details="Syntax check passed.",
                )
            )
        except SyntaxError as exc:
            results.append(
                CheckResult(
                    name=f"compile:{relative_name}",
                    passed=False,
                    details=f"SyntaxError at line {exc.lineno}, column {exc.offset}: {exc.msg}",
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    name=f"compile:{relative_name}",
                    passed=False,
                    details=f"{type(exc).__name__}: {exc}",
                )
            )
    return results


def run_unit_tests(run_dir: Path, test_file: str, timeout_seconds: int = 120) -> CheckResult:
    """Run the generated unittest suite inside the generated run folder."""
    test_path = run_dir / test_file
    stdout_path = run_dir / "validation_test_stdout.log"
    stderr_path = run_dir / "validation_test_stderr.log"

    if not test_path.exists():
        return CheckResult(
            name="unit_tests",
            passed=False,
            details=f"Test file not found: {test_file}",
        )

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(run_dir) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")

    command = [sys.executable, "-m", "unittest", test_file]
    try:
        completed = subprocess.run(
            command,
            cwd=run_dir,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        _write_text(stdout_path, completed.stdout or "")
        _write_text(stderr_path, completed.stderr or "")
        passed = completed.returncode == 0
        details = (
            f"Command: {' '.join(command)}\n"
            f"Exit code: {completed.returncode}\n"
            f"STDOUT saved to: {stdout_path.name}\n"
            f"STDERR saved to: {stderr_path.name}\n"
        )
        if completed.stdout:
            details += "\nSTDOUT preview:\n" + completed.stdout[-2000:]
        if completed.stderr:
            details += "\nSTDERR preview:\n" + completed.stderr[-4000:]
        return CheckResult(
            name="unit_tests",
            passed=passed,
            details=details,
            log_file=str(stderr_path if completed.stderr else stdout_path),
        )
    except subprocess.TimeoutExpired as exc:
        _write_text(stdout_path, exc.stdout or "")
        _write_text(stderr_path, exc.stderr or "Timed out while running generated tests.")
        return CheckResult(
            name="unit_tests",
            passed=False,
            details=f"Generated tests timed out after {timeout_seconds} seconds.",
            log_file=str(stderr_path),
        )



def run_app_import_smoke_test(run_dir: Path, app_file: str, timeout_seconds: int = 30) -> CheckResult:
    """Import the generated Gradio app to catch construction-time UI errors.

    Syntax checks cannot catch invalid Gradio object construction. This smoke test imports
    app.py in a subprocess with the generated folder on PYTHONPATH. Because generated apps
    must launch only inside the __main__ guard, importing should build components but not
    start the web server.
    """
    app_path = run_dir / app_file
    stdout_path = run_dir / "validation_app_import_stdout.log"
    stderr_path = run_dir / "validation_app_import_stderr.log"

    if not app_path.exists():
        return CheckResult(
            name="app_import_smoke_test",
            passed=False,
            details=f"App file not found: {app_file}",
        )

    module_name = Path(app_file).stem
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(run_dir) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    command = [sys.executable, "-c", f"import {module_name}"]

    try:
        completed = subprocess.run(
            command,
            cwd=run_dir,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        _write_text(stdout_path, completed.stdout or "")
        _write_text(stderr_path, completed.stderr or "")
        details = (
            f"Command: {' '.join(command)}\n"
            f"Exit code: {completed.returncode}\n"
            f"STDOUT saved to: {stdout_path.name}\n"
            f"STDERR saved to: {stderr_path.name}\n"
        )
        if completed.stderr:
            details += "\nSTDERR preview:\n" + completed.stderr[-4000:]
        if completed.stdout:
            details += "\nSTDOUT preview:\n" + completed.stdout[-2000:]
        return CheckResult(
            name="app_import_smoke_test",
            passed=completed.returncode == 0,
            details=details if completed.returncode != 0 else "Generated app imports successfully without launching the server.",
            log_file=str(stderr_path if completed.stderr else stdout_path),
        )
    except subprocess.TimeoutExpired as exc:
        _write_text(stdout_path, exc.stdout or "")
        _write_text(stderr_path, exc.stderr or "Timed out while importing generated app.")
        return CheckResult(
            name="app_import_smoke_test",
            passed=False,
            details=f"Generated app import timed out after {timeout_seconds} seconds. Ensure app.launch() is inside if __name__ == '__main__'.",
            log_file=str(stderr_path),
        )


USER_FACING_TABLE_KEYWORDS = {
    "record", "records", "list", "lists", "table", "row", "rows",
    "transaction", "transactions", "expense", "expenses", "task", "tasks",
    "product", "products", "order", "orders", "customer", "customers",
    "user", "users", "inventory", "stock", "appointment", "appointments",
    "booking", "bookings", "invoice", "invoices", "employee", "employees",
    "student", "students", "lead", "leads", "ticket", "tickets", "case", "cases",
    "filter", "search", "sort", "ranking", "recommendation", "recommendations",
    "history", "log", "logs", "schedule", "calendar", "catalog", "directory",
}

REPORT_OR_SUMMARY_KEYWORDS = {
    "summary", "report", "analytics", "dashboard", "total", "average", "score",
    "kpi", "metric", "insight", "analysis", "explanation", "recommend", "forecast",
}

RAW_JSON_ALLOWED_KEYWORDS = {
    "raw json", "json output", "api response", "debug", "schema", "payload",
    "developer", "webhook", "nested json", "configuration json",
}


def _contains_any(text: str, keywords: set[str]) -> bool:
    """Return True when any keyword appears in the normalized text."""
    return any(keyword in text for keyword in keywords)

def validate_gradio_display_quality(run_dir: Path, app_file: str, requirements: str) -> CheckResult:
    """Check that generated Gradio apps choose user-friendly output components.

    The check encourages adaptive product UI behavior. It flags raw JSON output when
    the requirements suggest tables, records, summaries, or general user-facing results.
    """
    app_path = run_dir / app_file
    if not app_path.exists():
        return CheckResult(
            name="ui_display_quality",
            passed=False,
            details=f"App file not found: {app_file}",
        )

    content = _read_text(app_path)
    lower_requirements = requirements.lower()
    lower_content = content.lower()

    table_like_requirement = _contains_any(lower_requirements, USER_FACING_TABLE_KEYWORDS)
    summary_like_requirement = _contains_any(lower_requirements, REPORT_OR_SUMMARY_KEYWORDS)
    raw_json_requested = _looks_like_explicit_raw_json_request(requirements)

    uses_interface_component = "gr.interface" in lower_content or "gradio.interface" in lower_content
    if uses_interface_component:
        return CheckResult(
            name="ui_display_quality",
            passed=False,
            details=(
                "The generated app uses gr.Interface. AutoDev Crew requires gr.Blocks for generated product apps "
                "because Blocks supports multi-step workflows, tabs, tables, custom layout, and import-safe validation. "
                "Replace gr.Interface with `with gr.Blocks(title=...) as app:` and place app.launch() only inside the __main__ guard."
            ),
        )

    uses_json_component = "gr.json" in lower_content or "gradio.json" in lower_content
    uses_dataframe_component = "gr.dataframe" in lower_content or "gradio.dataframe" in lower_content
    uses_readable_summary_component = any(
        marker in lower_content
        for marker in ["gr.markdown", "gr.number", "gr.label", "gr.textbox", "gr.dataframe"]
    )
    has_table_formatter = any(
        marker in lower_content
        for marker in [
            "records_to_rows", "objects_to_rows", "to_rows", "format_records",
            "format_table", "doctors_to_rows", "patients_to_rows", "appointments_to_rows",
            "products_to_rows", "tickets_to_rows", "invoices_to_rows", "expenses_to_rows",
            "tasks_to_rows", "rows.append", "return rows"
        ]
    )
    has_cell_normalizer = any(
        marker in lower_content
        for marker in [
            "format_cell", "normalize_cell", "safe_cell", "join(map(str", "', '.join",
            '", ".join', "json.dumps", "isinstance(value, (list, dict",
            "isinstance(value, list", "isinstance(value, dict", "str(value)"
        ]
    )

    if raw_json_requested:
        return CheckResult(
            name="ui_display_quality",
            passed=True,
            details="Raw JSON output appears acceptable because the requirements explicitly ask for raw JSON/API/debug-style output.",
        )

    if uses_json_component and table_like_requirement and not uses_dataframe_component:
        return CheckResult(
            name="ui_display_quality",
            passed=False,
            details=(
                "The requirements describe user-facing records, lists, filters, search results, or tabular workflows, "
                "but the Gradio app uses gr.JSON without gr.Dataframe. Use gr.Dataframe for collections of records, "
                "with formatter functions that convert backend dictionaries/objects into table rows."
            ),
        )

    if uses_json_component and summary_like_requirement and not uses_readable_summary_component:
        return CheckResult(
            name="ui_display_quality",
            passed=False,
            details=(
                "The requirements describe summaries, reports, analytics, or KPIs, but the app relies on raw JSON. "
                "Use gr.Markdown, gr.Number, gr.Label, or summary tables for user-facing analytics."
            ),
        )

    if uses_json_component and not (uses_dataframe_component or uses_readable_summary_component):
        return CheckResult(
            name="ui_display_quality",
            passed=False,
            details=(
                "The app uses gr.JSON as the main visible output even though the requirements do not ask for raw JSON. "
                "Choose a display component that matches the workflow: gr.Dataframe for records, gr.Markdown for reports, "
                "gr.Number for calculations, gr.Label for classification, gr.File for downloads, or gr.Textbox for plain text."
            ),
        )

    if uses_dataframe_component and table_like_requirement and not (has_table_formatter and has_cell_normalizer):
        return CheckResult(
            name="ui_display_quality",
            passed=False,
            details=(
                "The app uses gr.Dataframe for table-like requirements, but it does not clearly define formatter/normalizer helpers "
                "that convert backend records into explicit rows with primitive scalar cells. Add helpers such as format_cell(), "
                "records_to_rows(), doctors_to_rows(), patients_to_rows(), or appointments_to_rows(). Dataframe cells must not "
                "contain raw dictionaries, lists, sets, or custom objects because the browser can render them as [object Object]."
            ),
        )

    if table_like_requirement and not uses_dataframe_component:
        return CheckResult(
            name="ui_display_quality",
            passed=True,
            details=(
                "The requirements appear table-like, but gr.Dataframe was not detected. This may still be acceptable for "
                "very small outputs; verify the generated UI presents records in a readable product-style format."
            ),
        )

    return CheckResult(
        name="ui_display_quality",
        passed=True,
        details="Gradio output components are acceptable for the inferred requirement shape.",
    )


def _read_validation_logs(run_dir: Path) -> Dict[str, str]:
    """Read validation log files so the repair model sees full failure context."""
    logs: Dict[str, str] = {}
    for name in ["validation_test_stdout.log", "validation_test_stderr.log"]:
        path = run_dir / name
        if path.exists():
            text = _read_text(path)
            logs[name] = text[-12000:]
    return logs


def _looks_like_explicit_raw_json_request(requirements_text: str) -> bool:
    """Detect explicit requests for raw JSON/API/debug output rather than incidental mentions."""
    text = requirements_text.lower()
    explicit_patterns = [
        "raw json", "json output", "return json", "display json", "show json",
        "api response", "debug output", "schema output", "json schema",
        "webhook payload", "developer payload",
    ]
    return any(pattern in text for pattern in explicit_patterns)


def validate_gradio_tab_completeness(run_dir: Path, app_file: str, requirements: str) -> CheckResult:
    """Detect empty or placeholder Gradio tabs in generated product apps.

    Import-time smoke tests catch construction errors, but they do not prove that every tab
    contains useful UI. This source-level check flags tabs that have no meaningful components,
    outputs, or button actions before the next sibling tab block begins.
    """
    app_path = run_dir / app_file
    if not app_path.exists():
        return CheckResult(
            name="ui_tab_completeness",
            passed=False,
            details=f"App file not found: {app_file}",
        )

    content = _read_text(app_path)
    lines = content.splitlines()
    tab_pattern = re.compile(r"^(?P<indent>\s*)with\s+gr\.Tab(?:Item)?\s*\(\s*[\"'](?P<name>[^\"']+)[\"']")
    component_markers = [
        "gr.Textbox", "gr.Number", "gr.Dropdown", "gr.Checkbox", "gr.Radio", "gr.Slider",
        "gr.Button", "gr.Markdown", "gr.Dataframe", "gr.File", "gr.Label", "gr.DateTime",
        "gr.Row", "gr.Column", ".click(", ".change(", ".submit(", "gr.UploadButton",
    ]
    placeholder_markers = ["pass", "todo", "placeholder", "coming soon", "not implemented"]

    tabs: List[Tuple[str, int, int, str]] = []
    for index, line in enumerate(lines):
        match = tab_pattern.match(line)
        if not match:
            continue
        indent_len = len(match.group("indent"))
        end_index = len(lines)
        for next_index in range(index + 1, len(lines)):
            next_line = lines[next_index]
            next_match = tab_pattern.match(next_line)
            if next_match and len(next_match.group("indent")) <= indent_len:
                end_index = next_index
                break
        body = "\n".join(lines[index + 1 : end_index])
        tabs.append((match.group("name"), index + 1, end_index, body))

    if not tabs:
        return CheckResult(
            name="ui_tab_completeness",
            passed=False,
            details="No gr.Tab or gr.TabItem sections were detected. Generated product apps should expose workflow sections as tabs.",
        )

    empty_or_placeholder: List[str] = []
    no_actions: List[str] = []
    for tab_name, start, _end, body in tabs:
        stripped = body.strip()
        lowered = stripped.lower()
        marker_count = sum(1 for marker in component_markers if marker in body)
        has_action = any(marker in body for marker in [".click(", ".change(", ".submit("])
        has_output_component = any(marker in body for marker in ["gr.Markdown", "gr.Dataframe", "gr.Textbox", "gr.Number", "gr.Label", "gr.File", "gr.JSON"])
        is_placeholder = any(marker in lowered for marker in placeholder_markers) and marker_count <= 2
        if not stripped or marker_count < 2 or is_placeholder:
            empty_or_placeholder.append(f"{tab_name} at line {start}")
        elif not has_action and not has_output_component:
            no_actions.append(f"{tab_name} at line {start}")

    if empty_or_placeholder:
        return CheckResult(
            name="ui_tab_completeness",
            passed=False,
            details=(
                "The generated Gradio app has empty or placeholder tabs: "
                + ", ".join(empty_or_placeholder)
                + ". Every requested workflow tab must contain visible inputs/outputs and working callbacks."
            ),
        )

    if no_actions:
        return CheckResult(
            name="ui_tab_completeness",
            passed=False,
            details=(
                "The generated Gradio app has tabs without useful actions or outputs: "
                + ", ".join(no_actions)
                + ". Add buttons/callbacks or visible outputs for these sections."
            ),
        )

    return CheckResult(
        name="ui_tab_completeness",
        passed=True,
        details=f"Detected {len(tabs)} non-empty Gradio workflow tabs with visible UI content.",
    )


def validate_gradio_callback_robustness(run_dir: Path, app_file: str) -> CheckResult:
    """Encourage callback functions to catch errors and return messages instead of red Gradio popups."""
    app_path = run_dir / app_file
    if not app_path.exists():
        return CheckResult(
            name="ui_callback_robustness",
            passed=False,
            details=f"App file not found: {app_file}",
        )

    content = _read_text(app_path)
    try:
        tree = ast.parse(content, filename=str(app_path))
    except SyntaxError as exc:
        return CheckResult(
            name="ui_callback_robustness",
            passed=False,
            details=f"Cannot inspect callbacks because app.py has syntax error: {exc}",
        )

    callback_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"click", "submit", "change"}:
            if node.args:
                first = node.args[0]
                if isinstance(first, ast.Name):
                    callback_names.add(first.id)
            for keyword in node.keywords:
                if keyword.arg == "fn" and isinstance(keyword.value, ast.Name):
                    callback_names.add(keyword.value.id)

    function_nodes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    missing = sorted(name for name in callback_names if name not in function_nodes)
    if missing:
        return CheckResult(
            name="ui_callback_robustness",
            passed=False,
            details="Callbacks referenced by UI events are missing function definitions: " + ", ".join(missing),
        )

    risky: List[str] = []
    for name in sorted(callback_names):
        node = function_nodes.get(name)
        if not node:
            continue
        has_try = any(isinstance(child, ast.Try) for child in ast.walk(node))
        # View/list callbacks may be simple and safe; mutation/report callbacks should handle errors.
        mutation_or_report_name = any(token in name.lower() for token in [
            "add", "create", "update", "delete", "cancel", "receive", "record", "book",
            "generate", "calculate", "summary", "report", "filter", "search", "deactivate",
        ])
        if mutation_or_report_name and not has_try:
            risky.append(name)

    if risky:
        return CheckResult(
            name="ui_callback_robustness",
            passed=False,
            details=(
                "These UI callback functions perform user actions or reports without local try/except handling: "
                + ", ".join(risky)
                + ". Wrap callbacks so user-facing errors return readable messages instead of Gradio red error popups."
            ),
        )

    return CheckResult(
        name="ui_callback_robustness",
        passed=True,
        details=f"Detected {len(callback_names)} UI callbacks with acceptable definitions and error-handling structure.",
    )



def build_dynamic_gradio_fallback_app(inputs: Dict[str, Any]) -> str:
    """Build a deterministic Gradio app from the generated backend public API."""
    project_name = str(inputs.get("project_name") or "Generated Application")
    module_import = str(inputs.get("module_import") or Path(inputs.get("module_file", "app_module.py")).stem)
    class_name = str(inputs.get("class_name") or "GeneratedApp")

    return f"""import inspect
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any

import gradio as gr
import pandas as pd

from {module_import} import {class_name}


_instance = {class_name}()


ACTION_PREFIXES = (\"add_\", \"create_\", \"update_\", \"delete_\", \"remove_\", \"deactivate_\", \"activate_\", \"cancel_\", \"receive_\", \"record_\", \"book_\", \"mark_\", \"change_\", \"set_\")
LIST_PREFIXES = (\"list_\", \"view_\", \"get_all\", \"show_\", \"filter_\", \"search_\", \"find_\", \"identify_\")
REPORT_PREFIXES = (\"generate_\", \"calculate_\", \"summary\", \"report\", \"dashboard\", \"total_\", \"average_\", \"count_\", \"export_\")


def _titleize(name: str) -> str:
    return name.replace(\"_\", \" \" ).strip().title()


def _format_cell(value: Any) -> Any:
    # Convert any backend value into a scalar display-safe cell.
    if value is None:
        return \"\"
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return \"; \".join(f\"{{_format_cell(key)}}: {{_format_cell(val)}}\" for key, val in value.items())
    if isinstance(value, (list, tuple, set)):
        return \", \".join(str(_format_cell(item)) for item in value)
    if hasattr(value, \"__dict__\"):
        return _format_cell(vars(value))
    return str(value)


def _normalize_record(item: Any) -> dict[str, Any]:
    # Convert a backend record into a flat dictionary with scalar values.
    if is_dataclass(item):
        item = asdict(item)
    elif hasattr(item, \"__dict__\") and not isinstance(item, dict):
        item = vars(item)
    elif not isinstance(item, dict):
        item = {{\"value\": item}}
    return {{str(key): _format_cell(value) for key, value in item.items()}}


def _to_dataframe(value: Any) -> pd.DataFrame:
    # Convert arbitrary backend output into a safe pandas DataFrame for Gradio.
    if value is None:
        return pd.DataFrame(columns=[\"Result\"])

    if is_dataclass(value):
        value = asdict(value)

    if isinstance(value, dict):
        if all(not isinstance(v, (dict, list, tuple, set)) and not hasattr(v, \"__dict__\") for v in value.values()):
            return pd.DataFrame([{{\"Metric\": _format_cell(k), \"Value\": _format_cell(v)}} for k, v in value.items()])
        return pd.DataFrame([_normalize_record(value)])

    if isinstance(value, (list, tuple, set)):
        records = list(value)
        if not records:
            return pd.DataFrame(columns=[\"Result\"])
        normalized = [_normalize_record(item) for item in records]
        return pd.DataFrame(normalized)

    return pd.DataFrame([[_format_cell(value)]], columns=[\"Result\"])


def _to_markdown(value: Any) -> str:
    # Create readable Markdown from backend output without exposing raw JSON.
    if value is None:
        return \"✅ Operation completed.\"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return f\"**Result:** {{value}}\"
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        lines = [\"### Result\"]
        for key, val in value.items():
            lines.append(f\"- **{{_format_cell(key)}}:** {{_format_cell(val)}}\")
        return \"\\n\".join(lines)
    if isinstance(value, (list, tuple, set)):
        return f\"✅ Returned {{len(value)}} record(s). See the table below.\"
    return f\"**Result:** {{_format_cell(value)}}\"


def _parse_value(raw: str, annotation: Any, parameter_name: str) -> Any:
    # Best-effort conversion from UI textbox input to backend argument.
    text = \"\" if raw is None else str(raw).strip()
    lowered_name = parameter_name.lower()
    annotation_text = \"\" if annotation is inspect._empty else str(annotation).lower()

    if \"bool\" in annotation_text or lowered_name.startswith(\"is_\") or lowered_name.startswith(\"has_\") or lowered_name in {{\"active\", \"enabled\", \"completed\", \"status_flag\"}}:
        return text.lower() in {{\"true\", \"1\", \"yes\", \"y\", \"active\", \"enabled\", \"checked\"}}
    if \"int\" in annotation_text or lowered_name.endswith(\"quantity\") or lowered_name in {{\"quantity\", \"age\", \"count\", \"stock\", \"marks\", \"score\"}}:
        return int(float(text or \"0\"))
    if \"float\" in annotation_text or lowered_name.endswith(\"price\") or lowered_name.endswith(\"cost\") or lowered_name.endswith(\"fee\") or lowered_name in {{\"amount\", \"rate\", \"total\", \"value\", \"percentage\"}}:
        return float(text or \"0\")
    if \"list\" in annotation_text or \"ids\" in lowered_name or \"days\" in lowered_name or lowered_name.endswith(\"list\"):
        return [item.strip() for item in text.split(\",\") if item.strip()]
    if \"dict\" in annotation_text or \"answers\" in lowered_name or \"mapping\" in lowered_name:
        if text.startswith(\"{{\"):
            try:
                return json.loads(text)
            except Exception:
                pass
        pairs = {{}}
        for part in text.split(\",\"):
            if \"=\" in part:
                key, val = part.split(\"=\", 1)
                pairs[key.strip()] = val.strip()
        return pairs if pairs else text
    if text.startswith(\"{{\") or text.startswith(\"[\"):
        try:
            return json.loads(text)
        except Exception:
            return text
    return text


def _placeholder_for(parameter: inspect.Parameter) -> str:
    name = parameter.name.lower()
    if \"email\" in name:
        return \"name@example.com\"
    if \"phone\" in name:
        return \"9876543210\"
    if \"date\" in name:
        return \"2026-04-29\"
    if \"time\" in name:
        return \"10:30\"
    if \"days\" in name:
        return \"Monday, Tuesday, Friday\"
    if \"ids\" in name or name.endswith(\"list\"):
        return \"ID001, ID002\"
    if \"answers\" in name:
        return \"Q001=A, Q002=B\"
    if \"status\" in name:
        return \"Enter a supported status\"
    if \"quantity\" in name or \"amount\" in name or \"price\" in name or \"cost\" in name or \"fee\" in name:
        return \"100\"
    return \"Enter value\"


def _invoke(method_name: str, *raw_values: str):
    # Invoke a backend method safely and return Markdown plus a safe dataframe.
    try:
        method = getattr(_instance, method_name)
        signature = inspect.signature(method)
        parameters = list(signature.parameters.values())
        args = []
        for parameter, raw_value in zip(parameters, raw_values):
            args.append(_parse_value(raw_value, parameter.annotation, parameter.name))
        result = method(*args)
        return _to_markdown(result), _to_dataframe(result)
    except Exception as exc:
        return f\"❌ {{type(exc).__name__}}: {{exc}}\", pd.DataFrame(columns=[\"Result\"])


def _public_backend_methods():
    # Return public callable backend methods suitable for the generated UI.
    methods = []
    for name, member in inspect.getmembers(_instance, predicate=callable):
        if name.startswith(\"_\"):
            continue
        methods.append((name, member))
    return methods


def _group_for_method(name: str) -> str:
    lower = name.lower()
    if lower.startswith(ACTION_PREFIXES):
        return \"Actions\"
    if lower.startswith(LIST_PREFIXES):
        return \"Lists, Search & Filters\"
    if lower.startswith(REPORT_PREFIXES) or any(token in lower for token in [\"summary\", \"report\", \"dashboard\", \"total\", \"value\", \"margin\"]):
        return \"Reports & Analytics\"
    return \"Other Workflows\"


with gr.Blocks(title=\"{project_name}\", css=\".gradio-container {{max-width: 1500px !important;}}\") as app:
    gr.Markdown(\"\"\"
    # {project_name}
    This interface was generated by AutoDev Crew's reliability layer from the backend public API.
    It exposes available workflows with safe inputs, readable messages, and table-safe outputs.
    \"\"\")

    methods = _public_backend_methods()
    if not methods:
        gr.Markdown(\"No public backend methods were found to expose.\")
    else:
        grouped = {{\"Actions\": [], \"Lists, Search & Filters\": [], \"Reports & Analytics\": [], \"Other Workflows\": []}}
        for method_name, method in methods:
            grouped[_group_for_method(method_name)].append((method_name, method))

        for group_name, group_methods in grouped.items():
            if not group_methods:
                continue
            with gr.Tab(group_name):
                gr.Markdown(f\"## {{group_name}}\")
                for method_name, method in group_methods:
                    with gr.Accordion(_titleize(method_name), open=False):
                        signature = inspect.signature(method)
                        inputs = []
                        parameters = list(signature.parameters.values())
                        if parameters:
                            with gr.Row():
                                for parameter in parameters:
                                    component = gr.Textbox(
                                        label=_titleize(parameter.name),
                                        placeholder=_placeholder_for(parameter),
                                    )
                                    inputs.append(component)
                        else:
                            gr.Markdown(\"No input required for this workflow.\")
                        status = gr.Markdown(label=\"Status\")
                        table = gr.Dataframe(
                            value=pd.DataFrame(columns=[\"Result\"]),
                            interactive=False,
                            label=\"Table Output\",
                            wrap=True,
                        )
                        gr.Button(f\"Run {{_titleize(method_name)}}\").click(
                            fn=lambda *values, _method_name=method_name: _invoke(_method_name, *values),
                            inputs=inputs,
                            outputs=[status, table],
                        )


if __name__ == \"__main__\":
    app.launch()
"""

def apply_dynamic_gradio_fallback(inputs: Dict[str, Any], reason: str) -> CheckResult:
    # Replace a failing generated Gradio app with a deterministic introspection UI.
    run_dir = Path(inputs["run_output_dir"])
    app_file = inputs.get("app_file", "app.py")
    backup_path = run_dir / "app.generated_before_fallback.py"
    app_path = run_dir / app_file
    if app_path.exists() and not backup_path.exists():
        backup_path.write_text(app_path.read_text(encoding="utf-8"), encoding="utf-8")
    app_path.write_text(build_dynamic_gradio_fallback_app(inputs), encoding="utf-8")
    return CheckResult(
        name="dynamic_gradio_fallback",
        passed=True,
        details=(
            "Generated app.py was replaced with a deterministic introspection-based Gradio UI because the custom UI failed validation. "
            f"Reason: {reason}. Original app saved as {backup_path.name}."
        ),
        log_file=str(backup_path) if backup_path.exists() else None,
    )


def _has_ui_specific_failure(checks: List[CheckResult]) -> bool:
    # Return True when validation failures are related to Gradio/UI quality.
    ui_names = {"app_import_smoke_test", "ui_tab_completeness", "ui_callback_robustness", "ui_display_quality"}
    for check in checks:
        if check.passed:
            continue
        detail = check.details.lower()
        if check.name in ui_names or "gradio" in detail or "gr.interface" in detail or "[object object]" in detail:
            return True
    return False


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    """Extract the first JSON object from an LLM response."""
    text = raw_text.strip()
    text, _ = _strip_markdown_fence(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def attempt_openai_repair(inputs: Dict[str, Any], validation_summary: ValidationSummary, attempt_number: int) -> CheckResult:
    """Use OpenAI GPT-4o to repair generated files after failed validation.

    This is deliberately narrow: it only patches the backend module, Gradio app, and test file.
    It writes the raw repair response for auditability.
    """
    run_dir = Path(inputs["run_output_dir"])
    module_file = inputs["module_file"]
    app_file = inputs.get("app_file", "app.py")
    test_file = inputs["test_file"]
    response_path = run_dir / f"repair_attempt_{attempt_number}_response.txt"

    if not os.getenv("OPENAI_API_KEY"):
        return CheckResult(
            name=f"repair_attempt_{attempt_number}",
            passed=False,
            details="OPENAI_API_KEY is missing, so the GPT-4o repair loop could not run.",
        )

    try:
        from openai import OpenAI
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name=f"repair_attempt_{attempt_number}",
            passed=False,
            details=f"Could not import OpenAI SDK. Install dependency `openai`. Error: {exc}",
        )

    def maybe_read(relative_name: str) -> str:
        path = run_dir / relative_name
        return _read_text(path) if path.exists() else ""

    failed_checks = [check.__dict__ for check in validation_summary.checks if not check.passed]
    validation_logs = _read_validation_logs(run_dir)
    prompt = f"""
You are the AutoDev Crew repair engineer.

Repair the generated Python project so it passes syntax validation, unittest execution, and product-style UI validation.
Prioritize fixing the exact failing traceback, then run a mental consistency check across backend methods, frontend callbacks, and unittest expectations.
Return ONLY a JSON object with exactly these keys:
- "{module_file}": full corrected raw Python code for the backend module
- "{app_file}": full corrected raw Python code for the Gradio app
- "{test_file}": full corrected raw Python code for the unittest file

Do not include markdown fences.
Do not omit unchanged files.
Keep the implementation aligned with these original requirements:
{inputs.get('requirements', '')}

Project metadata:
- Backend module import name: {inputs.get('module_import')}
- Primary class name: {inputs.get('class_name')}
- Frontend framework: Gradio only

Backend and test consistency requirements:
- Make the backend public API, method names, return values, class constants, and validation behavior internally consistent.
- If tests call a method, constant, or attribute that should exist according to the requirements, implement it in the backend.
- If tests invented a wrong expectation that conflicts with the requirements, correct the test to verify the intended behavior instead of preserving the wrong assertion.
- Fix pluralization and enum-name mistakes such as STATUS/STATUSES, CATEGORY/CATEGORIES, PRIORITY/PRIORITIES, and avoid dynamic attribute names that can produce invalid names like STATUSS.
- Avoid brittle tests that depend on private implementation details unless the requirements explicitly require those details.
- Ensure every generated unittest can run with python -m unittest {test_file} from the generated folder.

Gradio UI requirements:
- Always use `with gr.Blocks(title=...) as app:` for the generated app. Do not use gr.Interface anywhere.
- A generated app must be importable with `import app` without launching a server or raising Gradio construction errors.
- Put `app.launch()` only inside `if __name__ == "__main__":`.
- Use `with gr.Tab("..."):` for workflow sections and make callback return values exactly match component outputs.
- Do not leave requested tabs empty or placeholder-only. Every tab must contain inputs/outputs and working actions for the workflow it represents.
- All user-action callbacks and report/dashboard callbacks must catch expected exceptions and return readable status messages instead of throwing red Gradio error popups.
- Dashboard/report callbacks must handle empty state safely with zero-value summaries or "No data available yet" messages.
- Infer the correct UI from the user's actual requirements; do not hardcode an expense/task/account pattern unless it fits.
- For user-facing records, lists, transactions, expenses, tasks, products, orders, users, inventory, bookings, schedules, recommendations, search results, or any collection of similarly shaped objects, use gr.Dataframe with clear headers.
- Convert list-of-dict/list-of-object backend results into table rows before returning them to gr.Dataframe.
- Every gr.Dataframe cell must be a primitive display-safe value: string, int, float, bool, None, or a date/time string. Never return raw dicts, lists, sets, dataclass objects, custom objects, or nested structures inside dataframe cells. Flatten or stringify nested values so the UI never shows [object Object].
- Add helper functions such as format_cell(), records_to_rows(), objects_to_rows(), doctors_to_rows(), patients_to_rows(), appointments_to_rows(), tickets_to_rows(), products_to_rows(), and summary_to_markdown() as appropriate to the domain.
- After create/update/delete actions, return a status message plus a refreshed display-safe table when the action affects a collection.
- For totals, summaries, reports, analytics, highest/lowest values, KPIs, and dashboard text, prefer gr.Markdown, gr.Dataframe, gr.Number, gr.Textbox, or gr.Label based on the result type.
- For calculators or single computed values, return compact text or numbers.
- For generated documents/content, use gr.Markdown or gr.Textbox.
- For generated files, use gr.File.
- Use gr.JSON only when the user explicitly asks for raw JSON/API/debug/schema output or when the nested structure cannot be represented clearly in a table or markdown.
- The UI should feel like a product interface, not a raw API output viewer.

Failed validation checks:
{json.dumps(failed_checks, indent=2)}

Full validation logs when available:
{json.dumps(validation_logs, indent=2)}

Current {module_file}:
{maybe_read(module_file)}

Current {app_file}:
{maybe_read(app_file)}

Current {test_file}:
{maybe_read(test_file)}
""".strip()

    try:
        client = OpenAI()
        completion = client.chat.completions.create(
            model="gpt-4o",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": "You repair generated Python projects. Return strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        raw_response = completion.choices[0].message.content or ""
        _write_text(response_path, raw_response)
        patch = _extract_json_object(raw_response)

        updated: List[str] = []
        for relative_name in [module_file, app_file, test_file]:
            value = patch.get(relative_name)
            if isinstance(value, str) and value.strip():
                cleaned_value, _ = _strip_markdown_fence(value)
                _write_text(run_dir / relative_name, cleaned_value.strip() + "\n")
                updated.append(relative_name)

        if len(updated) != 3:
            return CheckResult(
                name=f"repair_attempt_{attempt_number}",
                passed=False,
                details=(
                    "Repair response was parsed, but not all required files were returned. "
                    f"Updated files: {updated}. Raw response: {response_path.name}"
                ),
                log_file=str(response_path),
            )

        return CheckResult(
            name=f"repair_attempt_{attempt_number}",
            passed=True,
            details=f"GPT-4o repair patch applied to: {', '.join(updated)}. Raw response: {response_path.name}",
            log_file=str(response_path),
        )
    except Exception as exc:  # noqa: BLE001
        error_text = f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"
        _write_text(response_path, error_text)
        return CheckResult(
            name=f"repair_attempt_{attempt_number}",
            passed=False,
            details=f"Repair attempt failed. Details saved to {response_path.name}: {type(exc).__name__}: {exc}",
            log_file=str(response_path),
        )


def _collect_generated_files(run_dir: Path) -> List[str]:
    return [str(path.relative_to(run_dir)) for path in sorted(run_dir.rglob("*")) if path.is_file()]


def _write_reports(summary: ValidationSummary) -> None:
    run_dir = Path(summary.run_output_dir)
    json_path = run_dir / "validation_report.json"
    md_path = run_dir / "06_validation_report.md"

    _write_text(json_path, json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))

    status_icon = "✅" if summary.overall_passed else "❌"
    rows = []
    for check in summary.checks:
        status = '✅ Pass' if check.passed else '❌ Fail'
        details = check.details.replace('|', '\\|').replace(chr(10), '<br>')
        rows.append(f"| {status} | {check.name} | {details} |")

    report = f"""# AutoDev Crew Validation Report

{status_icon} **Overall status:** {'PASSED' if summary.overall_passed else 'FAILED'}

| Field | Value |
|---|---|
| Run ID | `{summary.run_id}` |
| Run Folder | `{summary.run_output_dir}` |
| Started At | {summary.started_at} |
| Completed At | {summary.completed_at} |
| Repair Attempts Requested | {summary.repair_attempts_requested} |
| Repair Attempts Used | {summary.repair_attempts_used} |

## Validation Checks

| Status | Check | Details |
|---|---|---|
{chr(10).join(rows)}

## Generated Files After Validation

```text
{chr(10).join(summary.generated_files)}
```

## Notes

- This quality gate performs deterministic local checks after the CrewAI generation workflow.
- Syntax validation uses Python AST parsing.
- Unit tests run with `python -m unittest <test_file>` from the generated run folder.
- If enabled, the repair loop uses OpenAI GPT-4o to patch generated files, then validation runs again.
"""
    _write_text(md_path, report)


def validate_generated_project(
    inputs: Dict[str, Any],
    *,
    repair_attempts: int = 1,
    run_tests: bool = True,
    test_timeout_seconds: int = 120,
) -> ValidationSummary:
    """Run the local quality gate for one generated project."""
    run_dir = Path(inputs["run_output_dir"])
    module_file = inputs["module_file"]
    app_file = inputs.get("app_file", "app.py")
    test_file = inputs["test_file"]
    python_files = [module_file, app_file, test_file]

    summary = ValidationSummary(
        run_id=inputs.get("run_id", run_dir.name),
        run_output_dir=str(run_dir),
        started_at=datetime.now().isoformat(timespec="seconds"),
        repair_attempts_requested=max(0, int(repair_attempts)),
    )

    for attempt_index in range(0, max(0, int(repair_attempts)) + 1):
        if attempt_index > 0:
            repair_result = attempt_openai_repair(inputs, summary, attempt_index)
            summary.repair_attempts_used += 1
            summary.checks.append(repair_result)
            if not repair_result.passed:
                break

        current_round_checks: List[CheckResult] = []
        current_round_checks.append(clean_generated_python_files(run_dir, python_files))
        current_round_checks.extend(compile_python_files(run_dir, python_files))
        current_round_checks.append(run_app_import_smoke_test(run_dir, app_file))
        current_round_checks.append(validate_gradio_tab_completeness(run_dir, app_file, str(inputs.get("requirements", ""))))
        current_round_checks.append(validate_gradio_callback_robustness(run_dir, app_file))
        current_round_checks.append(
            validate_gradio_display_quality(run_dir, app_file, str(inputs.get("requirements", "")))
        )
        if run_tests:
            current_round_checks.append(run_unit_tests(run_dir, test_file, timeout_seconds=test_timeout_seconds))
        else:
            current_round_checks.append(
                CheckResult(name="unit_tests", passed=True, details="Unit test execution skipped by user.")
            )

        summary.checks.extend(current_round_checks)
        if all(check.passed for check in current_round_checks):
            # A generated custom UI can pass static checks but still render raw JS objects
            # or produce brittle callback behavior in the browser. Unless explicitly disabled,
            # normalize app.py to a deterministic runtime built from the verified backend API.
            # The LLM-written app is preserved as app.generated_before_fallback.py.
            if os.getenv("AUTODEV_KEEP_LLM_APP", "false").lower() not in {"1", "true", "yes"}:
                fallback_result = apply_dynamic_gradio_fallback(
                    inputs,
                    "final safe UI normalization after backend, tests, and project checks passed",
                )
                summary.checks.append(fallback_result)
                fallback_checks: List[CheckResult] = []
                fallback_checks.append(clean_generated_python_files(run_dir, python_files))
                fallback_checks.extend(compile_python_files(run_dir, python_files))
                fallback_checks.append(run_app_import_smoke_test(run_dir, app_file))
                fallback_checks.append(validate_gradio_tab_completeness(run_dir, app_file, str(inputs.get("requirements", ""))))
                fallback_checks.append(validate_gradio_callback_robustness(run_dir, app_file))
                fallback_checks.append(validate_gradio_display_quality(run_dir, app_file, str(inputs.get("requirements", ""))))
                summary.checks.extend(fallback_checks)
                summary.overall_passed = all(check.passed for check in fallback_checks)
            else:
                summary.overall_passed = True
            break

        # After the final LLM repair opportunity, recover UI-specific failures with a deterministic
        # introspection-based Gradio app. This keeps generated projects usable even when a custom
        # model-generated UI has empty tabs, invalid Blocks/Interface usage, or unsafe table values.
        if attempt_index == max(0, int(repair_attempts)) and _has_ui_specific_failure(current_round_checks):
            failing_details = "; ".join(check.name for check in current_round_checks if not check.passed)
            fallback_result = apply_dynamic_gradio_fallback(inputs, failing_details)
            summary.checks.append(fallback_result)
            fallback_checks: List[CheckResult] = []
            fallback_checks.append(clean_generated_python_files(run_dir, python_files))
            fallback_checks.extend(compile_python_files(run_dir, python_files))
            fallback_checks.append(run_app_import_smoke_test(run_dir, app_file))
            fallback_checks.append(validate_gradio_tab_completeness(run_dir, app_file, str(inputs.get("requirements", ""))))
            fallback_checks.append(validate_gradio_callback_robustness(run_dir, app_file))
            fallback_checks.append(validate_gradio_display_quality(run_dir, app_file, str(inputs.get("requirements", ""))))
            if run_tests:
                fallback_checks.append(run_unit_tests(run_dir, test_file, timeout_seconds=test_timeout_seconds))
            else:
                fallback_checks.append(CheckResult(name="unit_tests", passed=True, details="Unit test execution skipped by user."))
            summary.checks.extend(fallback_checks)
            if all(check.passed for check in fallback_checks):
                summary.overall_passed = True
            break

    summary.completed_at = datetime.now().isoformat(timespec="seconds")
    summary.generated_files = _collect_generated_files(run_dir)
    _write_reports(summary)
    return summary


def validation_summary_to_markdown(summary: ValidationSummary) -> str:
    """Compact validation summary for CLI/dashboard display."""
    status = "✅ PASSED" if summary.overall_passed else "❌ FAILED"
    failed = [check for check in summary.checks if not check.passed]

    if not failed:
        failure_heading = "#### Failed Checks"
        failed_text = "None"
    elif summary.overall_passed:
        failure_heading = "#### Earlier Failed Checks Repaired"
        failed_text = "\n".join(
            f"- **{check.name}**: {check.details[:500]}" for check in failed[-5:]
        )
        failed_text += "\n\nThe final validation status is passed because a later repair/validation round succeeded."
    else:
        failure_heading = "#### Current Failed Checks"
        failed_text = "\n".join(
            f"- **{check.name}**: {check.details[:500]}" for check in failed[-5:]
        )

    return f"""
### Validation Status: {status}

| Field | Value |
|---|---|
| Run ID | `{summary.run_id}` |
| Repair Attempts Used | {summary.repair_attempts_used} |
| Report | `{Path(summary.run_output_dir) / '06_validation_report.md'}` |
| JSON | `{Path(summary.run_output_dir) / 'validation_report.json'}` |

{failure_heading}

{failed_text}
""".strip()
