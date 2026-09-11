# All-Sheet Visual QA Standard

**Rule:** `MEP-VISUAL-QA-001`  
**Status:** `LOCKED`  
**Gate revision:** `all-sheet-visual-qa/2`

The release candidate is the exact generated DXF. QA reopens that file without
mutation, reconciles every board with the approved manifest and creates retained
color, monochrome, overview and content-zoom previews for each sheet.

The 24 required controls are: per-sheet rendering; manifest reconciliation;
frame/page validation; real plot scale; architecture readability; mechanical
network readability; plotted text size; annotation overlap; symbol/connectivity
cross-check; engineering labels; route continuity/direction cross-check; visual
density; equipment/service clearance cross-check; riser/detail coverage;
schedule/note/legend coverage; color/monochrome survival; multiple zoom levels;
approved-baseline diff; destructive visual tests; per-sheet scoring; fail-closed
release; representative projects 4/6/8/10; independent human review evidence; and
release acceptance requiring every critical check to pass.

Automated visual QA does not replace engineering review. `PASS` means the rendered
artifact satisfies the automated visual contract. A `SUBMISSION_READY` claim also
requires reviewer identity, evidence SHA-256 and exact reviewed-sheet coverage.
Pre-Submission artifacts may truthfully carry `INPUT_REQUIRED` for that human step.
