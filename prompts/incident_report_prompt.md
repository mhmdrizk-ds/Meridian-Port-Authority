# Incident Report Prompt

## Purpose
Generate a structured incident report for port operations.

## Reported Incident
- Container: {{container_number}} ({{container_type}})
- Description: {{description}}

## Instructions

Analyze the incident details and include:

- Incident description.
- Affected container information: status {{container_status}}, hazmat {{hazmat_status}}, customs {{customs_hold_status}}.
- Risk level.
- Possible cause.
- Recommended actions.

## Output Format

Incident Summary:
Describe what happened.

Risk Assessment:
Explain the potential impact.

Recommended Actions:
List the steps required to resolve the issue.

Follow-up:
Mention any approvals or investigations needed.
