# Adaptive Generation Guide

AutoDev Crew is designed to generate small local software products from natural-language requirements. It does not assume that every request is a tracker, CRUD app, calculator, or dashboard. The agent prompts ask the system to infer the app category, data objects, user workflows, and the most suitable Gradio output components from the requirement itself.

## Supported product patterns

AutoDev Crew is best suited for local Python + Gradio prototypes such as:

- CRUD and tracker apps
- calculators and rule-based decision tools
- inventory/order/customer management prototypes
- scheduling and booking prototypes
- recommendation/search/listing tools using deterministic local logic
- quiz, worksheet, educational, and content-generation style tools
- reporting and analytics dashboards over in-memory data
- workflow assistants that transform structured inputs into structured outputs

## Output display policy

Generated apps should use components that match the user-facing result:

| Result type | Preferred UI component |
|---|---|
| Rows of records, filters, search results, histories, rankings | `gr.Dataframe` |
| Reports, explanations, summaries, formatted receipts, generated content | `gr.Markdown` or `gr.Textbox` |
| Single numeric result, KPI, score, total | `gr.Number` or compact text |
| Classification result | `gr.Label` or readable text |
| Downloadable artifact | `gr.File` |
| Explicit API/debug/schema output | `gr.JSON` |

Raw JSON should not be used for ordinary records, trackers, summaries, or business workflows unless the user explicitly asks for JSON.

## Validation support

The validation gate checks generated Python syntax, runs generated unit tests, and performs a UI display-quality check. If the generated Gradio app uses raw JSON for user-facing table-like data, the repair loop receives explicit instructions to rebuild the interface with more appropriate components.

## Practical scope

AutoDev Crew is meant to create strong local prototypes and portfolio-ready generated artifacts. It avoids hidden databases, paid third-party APIs, authentication systems, background workers, and cloud services unless the user explicitly requests them. For production deployment, the generated project should still be reviewed by a human engineer.


## Dataframe Rendering Contract

When a generated app uses `gr.Dataframe`, callbacks must return explicit rows with primitive scalar values only. A safe row is a list such as `["D001", "Dr. Sen", "General Medicine", "Monday, Tuesday", 800]`. A risky row is one that contains a raw dictionary, list, set, dataclass object, or custom object. Those values can render in the browser as `[object Object]`. Generated apps should include helper functions like `format_cell()`, `records_to_rows()`, `doctors_to_rows()`, `patients_to_rows()`, `appointments_to_rows()`, or domain-specific equivalents.

For multi-entity apps, each entity should have its own table headers and formatter so different record shapes remain readable. Create/update/delete actions should return a human-readable status message and, where useful, a refreshed table showing the affected collection.

## Resilience Update: Deterministic Gradio Fallback

AutoDev Crew now includes a deterministic UI fallback layer after the LLM repair loop. If a generated custom Gradio app fails UI validation because of invalid `gr.Interface` usage, empty tabs, missing callbacks, unsafe dataframe values, or construction-time Gradio errors, validation can replace `app.py` with an introspection-based `gr.Blocks` app.

The fallback app imports the generated backend class, discovers public backend methods, creates one tab per callable workflow, converts textbox inputs into basic Python types, catches runtime exceptions, and renders results as Markdown plus display-safe dataframes. The original model-generated app is preserved as `app.generated_before_fallback.py` for auditability.

This layer is designed to protect first-run user experience. It does not remove the need for good frontend generation prompts; instead, it acts as a safety net so the generated project remains usable even when the custom UI is imperfect.

## Safe UI Normalization

AutoDev Crew treats the backend implementation and tests as the source of truth. After the generated backend passes validation, AutoDev Crew can replace fragile UI code with a deterministic safe Gradio interface built from the backend public API.

This normalization step is intentionally conservative. It prioritizes reliable demos over visually bespoke but brittle generated UI. The resulting app groups public backend methods into action, list/filter/search, reporting, and miscellaneous workflow tabs. Each method receives a small form, a readable Markdown status area, and a table-safe output component.

All table outputs are converted through scalar cell normalization. Dictionaries, lists, dataclasses, custom objects, and nested structures are flattened into readable strings or pandas DataFrames before reaching Gradio.


## Public Access and API Key Handling

The studio uses a bring-your-own-key access model for public demos. A user must paste their own OpenAI API key in the dashboard before generation begins. This avoids exposing the project owner's API key and prevents public visitors from consuming the owner's OpenAI credits.
