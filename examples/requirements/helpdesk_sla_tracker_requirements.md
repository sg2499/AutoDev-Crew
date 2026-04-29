# Sample Requirements: Helpdesk SLA Tracker

Build a helpdesk SLA tracking app.

Each ticket should include ticket ID, customer name, issue category, priority, created datetime, response deadline, resolution deadline, status, assigned agent, and notes.

The system should create tickets, update status, assign agents, list tickets, filter by priority/status, identify tickets nearing SLA breach, identify breached tickets, calculate SLA compliance percentage, and generate SLA summary.

Prevent invalid deadlines, unsupported priorities/statuses, empty customer names, duplicate IDs, and updates to non-existing tickets.

The Gradio app should show tickets, nearing-breach tickets, and breached tickets as tables. SLA compliance summary should be Markdown metrics.
