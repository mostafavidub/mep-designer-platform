# Engineer Feedback and Quality Acceptance Standard

Every final engineering review carries a reviewer identity and a hash of its
external evidence. Private marked-up drawings are not stored in Git.

Each redline is classified as `project-specific`, `rulebook deficiency`, or
`engine bug`. Project-specific findings remain isolated to that project. A
rulebook deficiency can enter the shared system only with a Rule ID and a
regression test. An engine bug requires a reproducible fixture and regression
test. Open major or critical redlines block acceptance.

Final quantitative acceptance requires:

- structural/MEP clashes, routing warnings, unapproved penetrations,
  manufacturer violations, missing required details,
  plan/riser/schedule mismatches and major redlines equal zero;
- route efficiency at least 90 percent;
- equipment placement score at least 90/100;
- detail completeness at least 95 percent;
- every main plan score at least 85/100; and
- package average score at least 90/100.

Missing or malformed evidence is `INPUT_REQUIRED`. Any threshold violation is
FAIL. Scores are measured results, never substituted from benchmark targets.
