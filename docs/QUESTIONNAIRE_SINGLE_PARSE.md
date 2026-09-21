# Questionnaire single-parse contract

The architecture questionnaire must parse each submitted DXF only once.
Previously the analyzer first validated the complete file with `ezdxf` and
then immediately loaded the same complete file again for analysis.  On a real
project this duplicate parse consumed roughly ninety percent of endpoint time
and caused the Sites-to-engine request to exceed its runtime budget.

The canonical reader already performs strict loading and recovery.  The
questionnaire now uses that returned document directly.  If recovery was
required, the recovered document is saved to the extracted working copy before
analysis; the immutable customer upload remains untouched.

Verification requires the focused questionnaire regression, the repository
regression suite, local before/after timing with the same real architecture
file, and a successful Staging request through the customer panel.
