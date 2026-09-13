You are scoring a software/automation "problem" for a solo builder deciding what to build next.
Score each of the six dimensions as an integer 0–5 and justify it.

For every dimension return:
- `score`: integer 0–5
- `reason`: one line explaining the score
- `evidence_quote`: a **verbatim** quote from the supplied evidence that supports it (empty string only if no evidence supports it)

Dimensions (spec §6):
- `frequency`: How many independent people asked for this? Derive from the distinct-author count, not raw post count or upvotes.
- `pain`: How bad is the current workaround?
- `willingness_to_pay`: Is anyone demonstrably paying — a stated budget, a paid tool they hate, a hired human?
- `buildability`: Could one person ship a usable MVP in about four weeks?
- `fit`: Match to the operator's edge: rental property, education/tutoring, infra/devops, Python.
- `defensibility`: Is there a data or distribution advantage, or is this a weekend clone target?

Be calibrated and skeptical. Most problems are mediocre; reserve 4–5 for genuinely strong signals.
Do NOT apply the regulated-domain penalty yourself — it is applied downstream in code.
