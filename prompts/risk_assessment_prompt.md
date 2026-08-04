# Container Risk Assessment Prompt

## Purpose
Analyze container information and evaluate the risk level before performing any operation.

## Container Under Review
- Container: {{container_number}} ({{container_type}})

## Instructions

Review the following information:

- Container status: {{container_status}}
- Hazmat status: {{hazmat_status}}
- Customs hold status: {{customs_hold_status}}
- Carrier status: {{carrier_name}} — {{carrier_status}}
- Previous transactions.

Provide:

- Risk level.
- Main risk factors.
- Required approvals.
- Recommended action.

## Output Format

Risk Level:
Low / Medium / High

Risk Factors:
List the reasons affecting the risk.

Required Approvals:
Mention any required human approvals.

Recommendation:
Explain the next recommended step.
