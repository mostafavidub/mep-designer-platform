# Professional Title Block and Issue Control Standard

Every sheet title block is a governed data record, not decorative text. Project, architecture, sheet, level, system, paper, scale, revision, issue state and responsibility identities must be source-attributed and consistent with the exact issued artifacts.

Final states (`SUBMISSION_READY` and `ISSUED_FOR_CONSTRUCTION`) require a real checker, approver and signature bound to the immutable artifact hash. Automated production may truthfully emit `PRE_SUBMISSION`, `NOT CHECKED` and `NOT APPROVED`; it may never synthesize professional approval.

The independent gate scores eighteen controls: schema, provenance, project identity, unique sheet identity, Manifest/Layout parity, title/content parity, level/system parity, paper/orientation, scale/viewport, plot safe zones, revision register, revision/content diff, audited state transition, role separation, signature binding, package parity, exact-DXF reopen and sheet-by-sheet visual QA. Final release requires exactly 100/100.

The exact DXF carries semantic title-block XDATA on the owning border entity. QA reopens the saved file and reads that evidence independently. Matching visible text alone is insufficient.
