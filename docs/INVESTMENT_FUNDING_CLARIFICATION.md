# Approved Investment Hours clarification

The user explicitly approved this rule during the PR #66 remediation discussion. It supersedes the contradictory Investment / Plan Hours Not Billable wording in the v0.3.25.1 reconstruction specification and CIP-RR-016 for the new CIP-1.0.2 engine.

- Gross Task Hours = internally funded Investment Hours + Customer Billable Hours.
- Investment reallocates existing effort; it never adds or removes effort.
- Calculate PM, preparation, contingency, testing and all other effort-derived amounts from gross effort before applying funding allocations. Those amounts, schedule effort and duration remain unchanged by a funding-only change.
- Customer fees = Customer Billable Hours × billing rate.
- Investment cannot be negative or exceed gross Task Hours on its line; nonzero allocations require notes.
- Investment against a PM or contingency line is a separate allocation on that line, not a proportional recalculation of overhead.

Controlled example: Development Task Hours 152, Investment 52, Customer Billable 100. The work still requires 152 Development hours and unchanged dependent effort.

CIP-1.0.2 implements this model. Locked historical revisions keep their original engine and commercial semantics. MEP does not yet expose this funding-allocation capability; this remediation fixes MEP adjustment persistence without claiming that feature exists for MEP.

Independent verification: `tests/test_investment_funding_invariant.py`, `tests/test_investment_schedule_funding.py`, the CIP browser smoke journey, and the Explain regression. Historical Golden scenarios remain on their versioned baseline.
