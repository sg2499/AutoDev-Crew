# Sample Requirements: Diagnostic Test Booking Manager

Build a diagnostic test booking app.

Each booking should include booking ID, patient name, phone, test name, test category, booking date, appointment slot, collection type, payment status, booking status, and notes.

The system should create bookings, update booking status, update payment status, cancel bookings, list bookings, filter by test category, filter by date, identify pending payments, and generate daily booking summary.

Prevent empty patient names, invalid phone numbers, unsupported statuses, invalid dates, duplicate slots for the same test if applicable, and updates to non-existing bookings.

The Gradio app should display bookings, filtered bookings, and pending payments as tables. Daily summaries should be Markdown reports.
