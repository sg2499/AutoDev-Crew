# AutoDev Crew Stress-Test Matrix

Use this matrix to verify that generated apps adapt their UI and backend behavior to different problem types.

| Pattern | Expected UI Output | Example Files |
|---|---|---|
| Record CRUD apps | Dataframes for records, Markdown for summaries | CRM, tickets, inventory, leave tracker |
| Scheduling apps | Tables grouped by date/person, Markdown summaries | appointment scheduler, travel itinerary |
| Finance apps | Tables for records, Markdown/KPI summaries for totals | invoice manager, budget planner, loan tracker |
| Education apps | Tables for question banks/records, Markdown answer keys | quiz builder, gradebook, worksheet generator |
| Operations trackers | Tables for lists, high-risk/overdue/low-stock tables | bug tracker, risk register, dispatch tracker |
| Calculators | Number outputs and Markdown explanations | business calculator, unit converter |
| Content/document generators | Markdown previews and optional file output | document generator, content calendar |

## Recommended validation strategy

1. Start with a simple CRUD app.
2. Test a tracker with filters and summaries.
3. Test a calculator-style app.
4. Test a generator-style app.
5. Test a scheduling workflow.
6. Test an app with strict validation rules.

