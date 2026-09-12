# Questionnaire and Design Basis — 100-point standard

Every Submission Ready Mechanical run must pass the eighteen controls implemented
by `app.design_basis_questionnaire_gate`. The contract requires architecture facts,
attributed answer records, explicit system scope, dynamic question applicability,
governed prior-answer reuse, explicit cross-project authorization, canonical
normalization, numeric values with units and ranges, climate evidence, complete
system criteria, owner equipment preferences, regulatory facts, architecture
consistency, a valid dependency graph, an owner-approved summary, an immutable
revision, persistence/destructive QA and a closed generation decision.

Mechanical references are forbidden as generation inputs. Missing evidence is
`INPUT_REQUIRED`; contradictions or post-approval mutation are `FAIL`. Only all
controls `PASS` and an exact score of 100 permit Submission Ready. A content hash
binds answers, architecture SHA, rules revision and approval; any change creates a
new revision and requires renewed approval.
