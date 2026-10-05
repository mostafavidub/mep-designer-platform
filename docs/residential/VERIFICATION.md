# Verification evidence

Executed locally on Python3.12.13,2026-10-05:

- Focused: `python -m pytest tests/test_residential_foundation.py -q -p no:cacheprovider`: **28 passed,62 subtests passed**,2.32s.
- Full: `python -m pytest tests -q -p no:cacheprovider --disable-warnings`: **1432 passed,76 subtests passed**,88.38s. Environment: isolated temporary DATA_DIR/CAD_OUTPUT_DIR, disabled architecture vision provider, bytecode/cache disabled.5882 warnings retained; no failure hidden.
- Catalog schema and cross-reference tests include all nine catalogs,122 distinct reviewed plan records and all41 symbol types.
-104 QA scenarios are a future engine matrix and remain unexecuted. No assertion of104 passed plan-generation scenarios.
- No human architecture Golden exists; no Golden approval invented.
- Report export completed with122-plan audit, JSON envelopes and41 original SVGs. HTML browser rendering unverified: local `file:` URL was rejected by browser policy; no workaround used.

Final governance/identity checks and protected-file inventory are in `standards/test-suites/residential-verification.json`. CI results are reported on the draft PR; local tests do not imply CI success.

Final focused+governance rerun after the output-proof schema addition: **52 passed,62 subtests**,6.03s (29 foundation tests plus23 governance tests). Full-suite count above is the actual earlier1432-test run; the additional output-schema test was validated in this final focused run.
