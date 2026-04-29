"""Gradio dashboard for AutoDev Crew.

The dashboard lets a user enter requirements, run the multi-agent workflow, inspect
generated files, view validation status, inspect deployment assets, and download the
packaged generated project.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import gradio as gr
from dotenv import load_dotenv

from engineering_team.main import DEFAULT_REQUIREMENTS, build_inputs, run_autodev_pipeline
from engineering_team.validation import validation_summary_to_markdown
from engineering_team.deployment import create_run_zip


def _safe_read(path: Path) -> str:
    """Read a text file safely for dashboard preview."""
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "This file is not a UTF-8 text file and cannot be previewed in the dashboard."




def _mask_key_for_status(api_key: str) -> str:
    """Return a non-sensitive display form for a user-provided API key."""
    api_key = (api_key or "").strip()
    if len(api_key) <= 10:
        return "provided" if api_key else "missing"
    return f"{api_key[:3]}...{api_key[-4:]}"


def _validate_user_openai_key(api_key: str) -> tuple[bool, str]:
    """Check that the dashboard user supplied an OpenAI API key before generation."""
    api_key = (api_key or "").strip()
    if not api_key:
        return False, "An OpenAI API key is mandatory to use AutoDev Crew Studio. Paste your own key to continue."
    if len(api_key) < 20:
        return False, "The OpenAI API key looks too short. Please paste a valid key from your OpenAI account."
    return True, ""

def _zip_run_folder(run_dir: Path) -> Path:
    """Create a zip archive for one generated run folder."""
    return create_run_zip(run_dir)


def _list_files(run_dir: Path) -> List[str]:
    """List generated text and project files relative to a run directory."""
    if not run_dir.exists():
        return []

    ignored_suffixes = {".zip", ".pyc", ".pyo"}
    ignored_parts = {"__pycache__", ".git"}
    files: List[str] = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in ignored_suffixes:
            continue
        if any(part in ignored_parts for part in path.parts):
            continue
        files.append(str(path.relative_to(run_dir)))
    return files


def _preferred_preview_file(files: List[str]) -> str | None:
    """Choose the most useful default file to display after a run completes."""
    preferred = [
        "run_manifest.json",
        "06_validation_report.md",
        "README_GENERATED_PROJECT.md",
        "01_product_spec.md",
        "02_architecture.md",
    ]
    for item in preferred:
        if item in files:
            return item
    return files[0] if files else None


def _format_file_index(files: List[str]) -> str:
    """Return a readable markdown index of generated files."""
    if not files:
        return "No generated files found yet. Run or load a project, then refresh the file list."
    lines = ["### Generated File Index", ""]
    for name in files:
        lines.append(f"- `{name}`")
    return "\n".join(lines)


def _dropdown_update(files: List[str]) -> Any:
    """Return a Gradio dropdown update with choices and a safe selected value."""
    selected = _preferred_preview_file(files)
    return gr.update(choices=files, value=selected, interactive=bool(files))


def _format_manifest(manifest: Dict[str, object]) -> str:
    """Return a compact markdown summary for the dashboard."""
    validation_value = manifest.get("validation_overall_passed", "Pending")
    if validation_value is True:
        validation_text = "✅ Passed"
    elif validation_value is False:
        validation_text = "❌ Failed"
    elif validation_value is None:
        validation_text = "Skipped"
    else:
        validation_text = str(validation_value)

    return f"""
### Run Summary

| Field | Value |
|---|---|
| Project | {manifest.get('project_name', '')} |
| Run ID | {manifest.get('run_id', '')} |
| Backend Module | {manifest.get('module_file', '')} |
| Primary Class | {manifest.get('class_name', '')} |
| Frontend | {manifest.get('frontend_framework', 'Gradio')} |
| LLM | {manifest.get('llm_model', 'openai/gpt-4o')} |
| Agents | {manifest.get('agent_count', '')} |
| Tasks | {manifest.get('task_count', '')} |
| Validation | {validation_text} |
| Repair Attempts Used | {manifest.get('repair_attempts_used', '')} |
| Output Folder | `{manifest.get('run_output_dir', '')}` |
""".strip()


def _read_validation_summary(run_dir: Path) -> str:
    """Read the generated validation report for dashboard display."""
    report = run_dir / "06_validation_report.md"
    if report.exists():
        return _safe_read(report)
    return "Validation report is not available yet."



def _read_production_summary(run_dir: Path) -> str:
    """Read deployment and production asset metadata for dashboard display."""
    manifest_path = run_dir / "production_manifest.json"
    deployment_path = run_dir / "DEPLOYMENT.md"
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            assets = "\n".join(f"- `{item}`" for item in data.get("deployment_assets", []))
            commands = "\n".join(f"- `{item}`" for item in data.get("recommended_local_commands", []))
            return f"""### Production Assets

| Field | Value |
|---|---|
| Workflow Version | {data.get('workflow_version', '1.0.0')} |
| Frontend | {data.get('frontend_framework', 'Gradio')} |
| LLM | {data.get('llm_model', 'openai/gpt-4o')} |
| Generated At | {data.get('generated_at', '')} |

#### Deployment Files

{assets}

#### Recommended Commands

{commands}
""".strip()
        except json.JSONDecodeError:
            return _safe_read(manifest_path)
    if deployment_path.exists():
        return _safe_read(deployment_path)
    return "Production assets are not available yet."


def run_autodev_from_dashboard(
    user_openai_api_key: str,
    project_name: str,
    requirements: str,
    module_name: str,
    class_name: str,
    output_root: str,
    repair_attempts: int,
    run_tests: bool,
) -> Tuple[str, str, str, Any, str, str | None, str, Dict[str, str], str]:
    """Run AutoDev Crew from dashboard inputs and return refreshed UI state."""
    load_dotenv()

    key_ok, key_error = _validate_user_openai_key(user_openai_api_key)
    if not key_ok:
        return (
            f"❌ **Access blocked.** {key_error}",
            "",
            "",
            gr.update(choices=[], value=None),
            "",
            None,
            "Generation is locked until the user provides their own OpenAI API key.",
            {},
            "No generated files available.",
        )

    if not requirements or not requirements.strip():
        return (
            "❌ **Requirements are required.** Please describe the software product you want AutoDev Crew to build.",
            "",
            "",
            gr.update(choices=[], value=None),
            "",
            None,
            "Run a project first to view production assets.",
            {},
            "No generated files available.",
        )

    args = SimpleNamespace(
        project_name=project_name or "AutoDev Generated Project",
        requirements=requirements.strip(),
        requirements_file=None,
        module_name=module_name or "generated_app",
        class_name=class_name or "GeneratedApp",
        frontend_framework="Gradio",
        output_root=output_root or "output",
        interactive=False,
    )

    previous_openai_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = user_openai_api_key.strip()

    try:
        inputs = build_inputs(args)
        pipeline_result = run_autodev_pipeline(
            inputs,
            run_validation=True,
            run_tests=bool(run_tests),
            repair_attempts=max(0, int(repair_attempts or 0)),
        )
        run_dir = Path(inputs["run_output_dir"])
        zip_path = _zip_run_folder(run_dir)
        files = _list_files(run_dir)
        selected_file = _preferred_preview_file(files)
        preview = _safe_read(run_dir / selected_file) if selected_file else "No generated files were found."
        validation_summary = pipeline_result.get("validation_summary")
        validation_markdown = (
            validation_summary_to_markdown(validation_summary)
            if validation_summary
            else _read_validation_summary(run_dir)
        )
        status = (
            f"✅ **AutoDev Crew completed.** Generated project folder: `{run_dir}`  \n"
            f"🔐 API key accepted for this run: `{_mask_key_for_status(user_openai_api_key)}`. "
            "The key is not written to generated files."
        )
        return (
            status,
            _format_manifest(inputs),
            validation_markdown,
            _dropdown_update(files),
            preview,
            str(zip_path),
            _read_production_summary(run_dir),
            {"run_dir": str(run_dir)},
            _format_file_index(files),
        )
    except Exception as exc:  # noqa: BLE001 - dashboard should show useful user-facing errors.
        return (
            f"❌ **AutoDev Crew failed:** `{type(exc).__name__}: {exc}`",
            "",
            "",
            gr.update(choices=[], value=None),
            "",
            None,
            "Generation failed before production assets could be created.",
            {},
            "Generation failed before files could be indexed.",
        )
    finally:
        if previous_openai_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = previous_openai_key

def preview_selected_file(file_name: str, state: Dict[str, str]) -> str:
    """Preview a selected generated file."""
    if not state or not state.get("run_dir"):
        return "Run AutoDev Crew first, then select a generated file to preview."
    if not file_name:
        return "Select a generated file to preview."

    run_dir = Path(state["run_dir"])
    target = (run_dir / file_name).resolve()

    try:
        target.relative_to(run_dir.resolve())
    except ValueError:
        return "Invalid file selection."

    return _safe_read(target)


def refresh_generated_files(state: Dict[str, str]) -> Tuple[Any, str, str]:
    """Refresh the generated file dropdown and preview for the active run."""
    if not state or not state.get("run_dir"):
        return gr.update(choices=[], value=None), "Run or load a project first.", "No generated files available."
    run_dir = Path(state["run_dir"])
    files = _list_files(run_dir)
    selected_file = _preferred_preview_file(files)
    preview = _safe_read(run_dir / selected_file) if selected_file else "No generated files were found."
    return _dropdown_update(files), preview, _format_file_index(files)


def refresh_recent_runs(output_root: str) -> Any:
    """Return a dropdown update containing recent generated run folders."""
    root = Path(output_root or "output")
    if not root.exists():
        return gr.update(choices=[], value=None)
    runs = [path.name for path in sorted(root.iterdir(), reverse=True) if path.is_dir()][:20]
    return gr.update(choices=runs, value=runs[0] if runs else None, interactive=bool(runs))


def load_existing_run(run_name: str, output_root: str) -> Tuple[str, str, str, Any, str, str | None, str, Dict[str, str], str]:
    """Load an existing run folder into the dashboard preview area."""
    if not run_name:
        return "Select a run folder first.", "", "", gr.update(choices=[], value=None), "", None, "Load a run first to view production assets.", {}, "No generated files available."

    run_dir = Path(output_root or "output") / run_name
    if not run_dir.exists() or not run_dir.is_dir():
        return f"Run folder not found: `{run_dir}`", "", "", gr.update(choices=[], value=None), "", None, "Run folder not found.", {}, "No generated files available."

    manifest_path = run_dir / "run_manifest.json"
    manifest_data: Dict[str, object] = {}
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest_data = {"run_id": run_name, "run_output_dir": str(run_dir)}
    else:
        manifest_data = {"run_id": run_name, "run_output_dir": str(run_dir)}

    zip_path = _zip_run_folder(run_dir)
    files = _list_files(run_dir)
    selected_file = _preferred_preview_file(files)
    preview = _safe_read(run_dir / selected_file) if selected_file else "No generated files were found."
    return (
        f"📂 Loaded existing run: `{run_dir}`",
        _format_manifest(manifest_data),
        _read_validation_summary(run_dir),
        _dropdown_update(files),
        preview,
        str(zip_path),
        _read_production_summary(run_dir),
        {"run_dir": str(run_dir)},
        _format_file_index(files),
    )


def create_dashboard() -> gr.Blocks:
    """Create and return the Gradio dashboard."""
    theme = gr.themes.Soft(
        primary_hue="orange",
        secondary_hue="slate",
        neutral_hue="slate",
        radius_size="lg",
    )

    custom_css = """
    .gradio-container {
        max-width: 1480px !important;
        margin: auto !important;
        background:
            radial-gradient(circle at 15% 5%, rgba(249, 115, 22, 0.20), transparent 26%),
            radial-gradient(circle at 85% 0%, rgba(59, 130, 246, 0.14), transparent 26%),
            linear-gradient(180deg, #09090b 0%, #111827 48%, #09090b 100%) !important;
    }
    .hero-card {
        padding: 34px 36px;
        border-radius: 28px;
        border: 1px solid rgba(255,255,255,0.12);
        background: linear-gradient(135deg, rgba(17,24,39,0.96), rgba(31,41,55,0.86));
        box-shadow: 0 28px 90px rgba(0,0,0,0.42);
        margin-bottom: 18px;
    }
    .hero-title {
        font-size: 44px;
        line-height: 1.05;
        font-weight: 900;
        letter-spacing: -1.4px;
        margin: 0 0 12px 0;
        background: linear-gradient(90deg, #ffffff, #fed7aa, #fb923c);
        -webkit-background-clip: text;
        color: transparent;
    }
    .hero-subtitle {
        font-size: 17px;
        color: #d1d5db;
        max-width: 1080px;
        margin-bottom: 22px;
    }
    .pill-row { display:flex; flex-wrap:wrap; gap:10px; margin-top: 12px; }
    .pill {
        display:inline-flex;
        align-items:center;
        gap:8px;
        padding: 8px 12px;
        border-radius: 999px;
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.12);
        color: #f9fafb;
        font-weight: 650;
        font-size: 13px;
    }
    .metric-grid {
        display:grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 14px;
        margin: 16px 0 18px 0;
    }
    .metric-card {
        padding: 18px 18px;
        border-radius: 18px;
        background: rgba(255,255,255,0.07);
        border: 1px solid rgba(255,255,255,0.10);
    }
    .metric-value { font-size: 24px; font-weight: 900; color: #fb923c; }
    .metric-label { font-size: 12px; color:#cbd5e1; text-transform:uppercase; letter-spacing:.08em; }
    .section-card {
        border-radius: 22px !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
        background: rgba(17,24,39,0.78) !important;
        box-shadow: 0 18px 50px rgba(0,0,0,0.26) !important;
        padding: 12px !important;
    }
    .demo-flow {
        padding: 22px 26px;
        border-radius: 22px;
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.12);
        margin-top: 20px;
    }
    button.primary, .primary button {
        font-weight: 800 !important;
    }
    textarea, input { border-radius: 12px !important; }
    .tabs button { font-weight: 700 !important; }
    @media (max-width: 900px) {
        .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .hero-title { font-size: 34px; }
    }
    """

    with gr.Blocks(title="AutoDev Crew Studio") as demo:
        state = gr.State({})

        gr.HTML(
            """
            <div class="hero-card">
                <div class="hero-title">AutoDev Crew Studio</div>
                <div class="hero-subtitle">
                    A bring-your-own-key GPT-4o powered multi-agent software factory that turns raw product requirements into
                    product specs, architecture, Python backend code, adaptive Gradio apps, tests, reviews,
                    validation reports, repair attempts, Docker assets, CI/CD workflow files, and downloadable project packages.
                </div>
                <div class="pill-row">
                    <span class="pill">🤖 CrewAI multi-agent SDLC</span>
                    <span class="pill">🔐 User API key required</span>
                    <span class="pill">🧠 OpenAI openai/gpt-4o only</span>
                    <span class="pill">🧪 Validation + repair loop</span>
                    <span class="pill">🎛 Adaptive Gradio UI generation</span>
                    <span class="pill">🐳 Docker + GitHub Actions</span>
                </div>
                <div class="metric-grid">
                    <div class="metric-card"><div class="metric-value">9</div><div class="metric-label">Specialized Agents</div></div>
                    <div class="metric-card"><div class="metric-value">57+</div><div class="metric-label">Stress-Test Examples</div></div>
                    <div class="metric-card"><div class="metric-value">3x</div><div class="metric-label">Default Repair Attempts</div></div>
                    <div class="metric-card"><div class="metric-value">ZIP</div><div class="metric-label">Generated Deliverable</div></div>
                </div>
            </div>
            """
        )

        with gr.Tabs():
            with gr.Tab("🚀 Generate Project"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=1, elem_classes=["section-card"]):
                        gr.Markdown("### Access Required")
                        gr.Markdown(
                            "🔐 **OpenAI API key is mandatory.** Each user must provide their own OpenAI key before running AutoDev Crew Studio. "
                            "This keeps public deployment safe: users run generations using their own account and credits."
                        )
                        user_openai_api_key = gr.Textbox(
                            label="Your OpenAI API Key (mandatory)",
                            placeholder="Paste your own OpenAI API key to unlock generation",
                            type="password",
                        )
                        gr.Markdown("### Project Controls")
                        project_name = gr.Textbox(
                            label="Project Name",
                            value="Task Manager AI",
                            placeholder="Example: Clinic Appointment Scheduler",
                        )
                        module_name = gr.Textbox(
                            label="Backend Module Name",
                            value="task_manager",
                            placeholder="Example: clinic_scheduler",
                        )
                        class_name = gr.Textbox(
                            label="Primary Class Name",
                            value="TaskManager",
                            placeholder="Example: ClinicScheduler",
                        )
                        output_root = gr.Textbox(
                            label="Output Root Folder",
                            value="output",
                        )
                        repair_attempts = gr.Number(
                            label="GPT-4o Repair Attempts",
                            value=3,
                            precision=0,
                            minimum=0,
                            maximum=5,
                        )
                        run_tests = gr.Checkbox(label="Run generated unit tests", value=True)
                        run_button = gr.Button("🚀 Generate + Validate Project", variant="primary", size="lg")

                    with gr.Column(scale=2, elem_classes=["section-card"]):
                        gr.Markdown("### Software Requirements")
                        requirements = gr.Textbox(
                            label="Describe the app you want AutoDev Crew to build",
                            value=(
                                "Build a lightweight project management app where users can create projects, add tasks, "
                                "update task status, filter by priority, view team workload, and generate a summary report."
                            ),
                            lines=18,
                            placeholder="Paste a detailed product requirement. Include entities, workflows, validations, UI expectations, and output formats when relevant.",
                        )

                with gr.Row():
                    with gr.Column(scale=1):
                        status = gr.Markdown(label="Status")
                    with gr.Column(scale=1):
                        manifest_summary = gr.Markdown(label="Run Summary")

            with gr.Tab("✅ Validation Report"):
                validation_report = gr.Markdown(
                    label="Validation Report",
                    value="Run AutoDev Crew to generate a validation report.",
                )

            with gr.Tab("📁 Generated Files"):
                with gr.Row():
                    with gr.Column(scale=1, elem_classes=["section-card"]):
                        file_choices = gr.Dropdown(
                            label="Generated Files",
                            choices=[],
                            interactive=True,
                            allow_custom_value=False,
                        )
                        refresh_files_button = gr.Button("🔄 Refresh Generated File List")
                        generated_file_index = gr.Markdown(
                            label="Generated File Index",
                            value="Run or load a project to view the generated file index.",
                        )
                    with gr.Column(scale=1, elem_classes=["section-card"]):
                        download_zip = gr.DownloadButton(label="⬇️ Download Generated Project ZIP", value=None, size="lg")
                        gr.Markdown(
                            """
                            ### Delivery Checklist
                            - Product spec
                            - Architecture
                            - Backend module
                            - Gradio app
                            - Unit tests
                            - Reviews and validation
                            - Docker/CI/CD/deployment assets
                            """
                        )
                file_preview = gr.Code(label="File Preview", language="markdown", lines=28)

            with gr.Tab("🚢 Production Assets"):
                production_summary = gr.Markdown(
                    label="Production Assets",
                    value="Run or load a project, then refresh this section to view Docker, CI/CD, and deployment metadata.",
                )
                refresh_production_button = gr.Button("🔄 Refresh Production Summary")

            with gr.Tab("🕘 Recent Runs"):
                with gr.Row():
                    recent_output_root = gr.Textbox(label="Output Root Folder", value="output")
                    refresh_button = gr.Button("🔄 Refresh Runs")
                recent_runs = gr.Dropdown(label="Recent Run Folders", choices=[], interactive=True)
                load_run_button = gr.Button("📂 Load Selected Run", size="lg")

        run_button.click(
            fn=run_autodev_from_dashboard,
            inputs=[user_openai_api_key, project_name, requirements, module_name, class_name, output_root, repair_attempts, run_tests],
            outputs=[status, manifest_summary, validation_report, file_choices, file_preview, download_zip, production_summary, state, generated_file_index],
        )

        file_choices.change(
            fn=preview_selected_file,
            inputs=[file_choices, state],
            outputs=[file_preview],
        )

        refresh_files_button.click(
            fn=refresh_generated_files,
            inputs=[state],
            outputs=[file_choices, file_preview, generated_file_index],
        )

        refresh_production_button.click(
            fn=lambda state: _read_production_summary(Path(state.get("run_dir", ""))) if state and state.get("run_dir") else "Run or load a project first.",
            inputs=[state],
            outputs=[production_summary],
        )

        refresh_button.click(
            fn=refresh_recent_runs,
            inputs=[recent_output_root],
            outputs=[recent_runs],
        )

        load_run_button.click(
            fn=load_existing_run,
            inputs=[recent_runs, recent_output_root],
            outputs=[status, manifest_summary, validation_report, file_choices, file_preview, download_zip, production_summary, state, generated_file_index],
        )

        gr.HTML(
            """
            <div class="demo-flow">
                <h3>Suggested demo flow</h3>
                <ol>
                    <li>Paste your own OpenAI API key to unlock the studio.</li>
                    <li>Enter a product idea with workflows, validations, and display expectations.</li>
                    <li>Run the agent team and let validation repair common generation mistakes.</li>
                    <li>Open the validation report to verify syntax, app-import smoke test, unit tests, and repair status.</li>
                    <li>Review generated files: product spec, architecture, backend, Gradio app, tests, reviews, README.</li>
                    <li>Inspect production assets: Dockerfile, Compose, GitHub Actions, .env.example, deployment guide.</li>
                    <li>Download the generated project ZIP and run the generated app locally.</li>
                </ol>
            </div>
            """
        )

    demo._autodev_theme = theme
    demo._autodev_css = custom_css
    return demo


def launch() -> None:
    """Launch the Gradio dashboard."""
    load_dotenv()
    demo = create_dashboard()
    launch_kwargs = {
        "theme": getattr(demo, "_autodev_theme", None),
        "css": getattr(demo, "_autodev_css", None),
    }
    launch_kwargs = {key: value for key, value in launch_kwargs.items() if value is not None}
    try:
        demo.launch(**launch_kwargs)
    except TypeError:
        # Older Gradio versions keep theme/css on Blocks rather than launch().
        demo.launch()


if __name__ == "__main__":
    launch()
