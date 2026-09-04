## Change summary

## SWCIS (mandatory)

- Change request: `changes/<id>.yaml`
- Canonical SWCIS version: `1.0.0`
- [ ] Every changed path is classified.
- [ ] Computed affected modules exactly match or are contained by the declared checklist.
- [ ] Required tests/docs/version bumps/migrations/diffs are linked as evidence.
- [ ] Every changed Rule ID has the complete PMM → engine → drawing → QA → regression → docs chain.
- [ ] Risk score and required owner reviews are complete.
- [ ] No bypass exists; any permitted waiver is versioned, independently reviewed, unexpired, and scoped.
- [ ] `python tools/swcis_validate.py --base <base-ref> --change-request changes/<id>.yaml` returns PASS.

## Verification

- [ ] Positive acceptance test
- [ ] Destructive/negative test
- [ ] Focused regression
- [ ] Golden-project regression
- [ ] Exact-file reopen
- [ ] Montage QA
- [ ] All required gates are PASS; none are SKIPPED

## 10-step governance impact

1. Single source of truth: not affected
2. Capability registry: not affected
3. Golden project: verified
4. Acceptance tests: verified
5. Semantic/numeric baseline: verified
6. Change impact matrix: verified
7. Fail-closed release pipeline: verified
8. Release snapshot: not affected
9. Protected merge/CI: verified
10. Contract change process: not affected

## Contract migration

- [ ] No locked behavior is weakened or removed.
- [ ] If locked behavior changes, an approved changelog entry and versioned migration are included.
