# Sample Requirements: Edible Oil Batch Production Tracker

Build an edible oil batch production tracking app.

Each batch should include batch ID, product type, raw material quantity, output oil quantity, production date, operator name, quality status, packaging size, units produced, wastage quantity, and notes.

The system should add production batches, update quality status, update packaging units, list batches, filter by product type, filter by quality status, calculate yield percentage, calculate total output, identify high-wastage batches, and generate production summary.

Prevent negative quantities, output greater than raw material unless explicitly noted, invalid dates, unsupported quality statuses, and updates to non-existing batches.

The Gradio app should show production batches and high-wastage batches as tables. Yield and production summaries should be readable Markdown metrics.
