# Sample Requirements: Rule-Based Text Classifier

Build a simple rule-based text classification app.

The system should allow users to create classification rules with rule ID, label, keyword list, priority, active status, and notes.

The system should classify input text based on active rules, list rules, update rules, delete rules, filter rules by label, show matched keywords, and generate classification summary.

Prevent empty labels, empty keyword lists, duplicate rule IDs, invalid priority values, and updates to non-existing rules.

The Gradio app should show rule lists and matched rule details as tables. Classification output should show the predicted label, confidence-style score, matched keywords, and explanation in readable Markdown.
