"""Lightweight run observability utilities for AutoDev Crew.

These utilities create deterministic trace and cost-estimate artifacts after each
run. They do not claim exact provider billing because CrewAI may abstract token
usage; instead, they provide an auditable local run trace and a transparent
estimated-cost placeholder that can be replaced with exact telemetry later.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _list_files(run_dir: Path) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file():
            files.append({"path": str(path.relative_to(run_dir)), "size_bytes": path.stat().st_size})
    return files


def write_observability_artifacts(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Write run trace, cost estimate, and production readiness report."""
    run_dir = Path(inputs["run_output_dir"])
    files = _list_files(run_dir)
    completed_at = datetime.now().isoformat(timespec="seconds")

    trace = {
        "run_id": inputs.get("run_id"),
        "project_name": inputs.get("project_name"),
        "workflow_version": "1.0.0",
        "created_at": inputs.get("created_at"),
        "completed_at": completed_at,
        "llm_model": inputs.get("llm_model", "openai/gpt-4o"),
        "frontend_framework": "Gradio",
        "agent_count": inputs.get("agent_count"),
        "task_count": inputs.get("task_count"),
        "validation_overall_passed": inputs.get("validation_overall_passed"),
        "deployment_assets_generated": inputs.get("deployment_assets_generated"),
        "files": files,
        "pipeline_stages": [
            "product_specification",
            "solution_architecture",
            "engineering_design",
            "backend_generation",
            "gradio_frontend_generation",
            "unit_test_generation",
            "code_review",
            "security_review",
            "documentation",
            "local_validation",
            "optional_repair_loop",
            "deployment_asset_generation",
            "packaging",
        ],
    }

    total_bytes = sum(item["size_bytes"] for item in files)
    cost_estimate = {
        "run_id": inputs.get("run_id"),
        "model": inputs.get("llm_model", "openai/gpt-4o"),
        "exact_token_usage_available": False,
        "note": (
            "CrewAI does not expose exact token/cost telemetry through this local artifact. "
            "Use provider dashboard or CrewAI tracing/observability integration for exact billing. "
            "This file records a transparent local artifact-size estimate only."
        ),
        "generated_file_count": len(files),
        "generated_total_bytes": total_bytes,
        "estimated_generated_tokens_from_file_size": round(total_bytes / 4),
    }

    readiness = f"""# Production Readiness Report

## Summary

| Field | Value |
|---|---|
| Run ID | `{inputs.get('run_id')}` |
| Project | {inputs.get('project_name')} |
| Workflow Version | 1.0.0 |
| LLM | {inputs.get('llm_model', 'openai/gpt-4o')} |
| Frontend | Gradio |
| Validation Passed | {inputs.get('validation_overall_passed')} |
| Deployment Assets Generated | {inputs.get('deployment_assets_generated')} |
| Generated File Count | {len(files)} |

## Included Production Assets

- Dockerfile
- Docker Compose file
- `.dockerignore`
- generated runtime requirements
- generated `.env.example`
- GitHub Actions CI workflow
- deployment guide
- production manifest
- run trace
- cost estimate placeholder

## Recommended Next Steps Before Real Deployment

1. Manually inspect generated backend, frontend, tests, security review, and validation report.
2. Add authentication and persistence if the generated product needs real users or stored data.
3. Replace sample/in-memory data with a production database where required.
4. Configure exact cost and trace collection through your preferred observability platform.
5. Test the Docker image locally before pushing to a cloud runtime.
"""

    _write_text(run_dir / "execution_trace.json", json.dumps(trace, indent=2, ensure_ascii=False))
    _write_text(run_dir / "cost_estimate.json", json.dumps(cost_estimate, indent=2, ensure_ascii=False))
    _write_text(run_dir / "PRODUCTION_READINESS_REPORT.md", readiness)

    return {
        "observability_artifacts_generated": True,
        "observability_completed_at": completed_at,
        "observability_files": [
            "execution_trace.json",
            "cost_estimate.json",
            "PRODUCTION_READINESS_REPORT.md",
        ],
    }
