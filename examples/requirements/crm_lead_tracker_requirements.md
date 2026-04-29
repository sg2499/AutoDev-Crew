# Sample Requirements: CRM Lead Tracker

Build a CRM lead tracking app for a small sales team.

The system should allow users to create leads with lead ID, customer name, company, email, phone, source, lead stage, estimated deal value, assigned salesperson, next follow-up date, and notes.

The system should allow users to:
- add a new lead
- update lead stage
- update assigned salesperson
- update follow-up date
- delete a lead
- list all leads
- filter leads by stage
- filter leads by salesperson
- search leads by customer name or company
- calculate total pipeline value
- calculate pipeline value by stage
- identify overdue follow-ups
- generate a sales pipeline summary

The system should prevent invalid operations such as invalid email, empty customer name, negative deal value, unsupported lead stage, and updating non-existing leads.

The Gradio app should display leads, filtered leads, overdue follow-ups, and search results as tables. Pipeline summaries should be displayed as readable Markdown metrics and summary tables.
