# Mechanical contract change process

Locked behavior may change only through a contract migration. Ordinary feature work cannot reduce or remove it.

1. Open a change record in `standards/contract-changelog.json` with rationale, affected projects and capabilities.
2. Mark the record `PROPOSED`; do not edit the approved baseline yet.
3. Add positive, destructive and golden-project tests demonstrating the intended behavior.
4. Record explicit owner approval by setting `approval.status` to `APPROVED` and identifying the approving decision.
5. Increase the affected contract/baseline schema or release version.
6. Provide forward and rollback migration instructions.
7. Run governance validation, focused regression, golden regression, exact reopen and montage QA.
8. Merge only when every required gate is `PASS`. `SKIPPED` is never acceptable.
9. Create a new immutable release snapshot; never rewrite an earlier approved snapshot.
10. Report the effect on all ten governance items in the task handoff.

Emergency changes follow the same process. There is no bypass flag.

