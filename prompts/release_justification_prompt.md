# Release Justification Prompt

## Purpose
Generate a clear justification for a container release decision.

## Container Under Review
- Container: {{container_number}} ({{container_type}})
- Requested by: {{requested_by}}

## Instructions

Analyze the container information and provide:

- Container status: {{container_status}}
- Customs status: {{customs_hold_status}}
- Hazmat status: {{hazmat_status}}
- Carrier status: {{carrier_name}} — {{carrier_status}}
- Approval requirements.

## Output Format

Decision:
Approved / Rejected / Requires Human Approval

Reason:
Explain why this decision was made.

Required Actions:
List any additional steps before release.
