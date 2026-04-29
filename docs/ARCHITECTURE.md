# AutoDev Crew Architecture

AutoDev Crew is a GPT-4o powered multi-agent software engineering workflow built with CrewAI. It accepts natural-language software requirements and produces a structured set of engineering artifacts: product specification, architecture, backend code, Gradio frontend, unit tests, code review, security review, generated-project README, validation reports, Docker assets, GitHub Actions workflow, deployment notes, and observability metadata.

## Agent Flow

```text
User Requirements
   ↓
Product Manager Agent
   ↓
Solution Architect Agent
   ↓
Engineering Lead Agent
   ↓
Backend Engineer Agent
   ↓
Gradio Frontend Engineer Agent
   ↓
Test Engineer Agent
   ↓
Code Reviewer Agent
   ↓
Security Reviewer Agent
   ↓
Documentation Agent
   ↓
Local Validation + Optional GPT-4o Repair
   ↓
Deployment Assets + Observability Artifacts
   ↓
Downloadable Project Package
```

## Runtime Components

| Component | Responsibility |
|---|---|
| `main.py` | CLI input parsing, manifest creation, crew kickoff, validation, deployment asset generation, and packaging. |
| `dashboard.py` | Gradio dashboard for entering requirements, running the crew, previewing files, loading previous runs, and downloading packages. |
| `crew.py` | CrewAI agent and task registration. |
| `config/agents.yaml` | Role, goal, backstory, and `openai/gpt-4o` model configuration for all agents. |
| `config/tasks.yaml` | Task prompts, context flow, expected outputs, and artifact output paths. |
| `validation.py` | Markdown fence cleanup, syntax validation, generated unit test execution, validation reports, and repair attempts. |
| `deployment.py` | Docker, Docker Compose, GitHub Actions, environment template, deployment guide, and production manifest generation. |
| `observability.py` | Local execution trace, artifact-size cost estimate, and production-readiness report. |

## Design Principles

- Use one LLM provider/model consistently: `openai/gpt-4o`.
- Keep the generated frontend target focused on Gradio.
- Generate timestamped runs so every output is traceable.
- Validate generated Python code before packaging.
- Preserve human review by generating code review and security review reports.
- Include production-readiness assets without pretending generated MVP code is automatically production-safe.

## Adaptive UI and Output Selection

The frontend-generation task includes an explicit output-selection policy. The generated Gradio app should infer the right display component from the requirement and backend return shape. Records and filtered lists should use tables, reports should use markdown, calculations should use compact numeric/text outputs, and raw JSON should be reserved for explicit API/debug use cases.

The validation layer includes a UI display-quality check that flags raw JSON when the requirement suggests a user-facing table/report experience. The optional GPT-4o repair loop can then patch the generated app to use more suitable Gradio components.

## Dashboard File Preview Reliability

The dashboard includes a generated-file index, a refreshable file dropdown, a direct download button for generated ZIP files, and a preview panel. This avoids treating the ZIP as a previewable file and keeps the generated artifacts easier to inspect after generation or after loading a previous run.
