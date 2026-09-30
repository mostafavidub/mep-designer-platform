# Architectural Golden Review v2

Golden Review v2 is a local, self-contained reviewer for producing human
architectural topology truth from an existing canonical proposal set. It does
not reconstruct architecture, invoke Vision, or grant proposal geometry any
engineering authority.

## Workflow and authority

1. A read-only export copies the current baseline envelope, Physical Space,
   label and Portal proposals with their original IDs, status and evidence.
2. The annotator assigns every proposal one disposition: `CORRECT`, `WRONG`,
   `EDITED`, or `UNSURE`. Unreviewed proposals never enter Golden truth.
3. Geometry can be edited with explicit undo/redo. Missing spaces, voids and
   portals can be drawn from the raw source.
4. Source-only completeness hides proposal and accepted overlays. The annotator
   must inspect all nine floor sectors and answer every omission question.
5. A different reviewer repeats a source-only pass before viewing the final
   overlay. Annotator and reviewer identities must differ.
6. Geometric adjacency and access connectivity are regenerated from accepted
   geometry. Windows cannot create access edges.
7. Approval fails closed while any proposal, critical issue, sector, required
   question, identity or geometry check is incomplete. Official benchmark
   scoring remains disabled for every status except `APPROVED`.

The existing `architectural-topology-golden/1.0` identity is preserved. New
fields are additive: `annotation_method`, `proposals`, `proposal_review_log`,
`completeness`, `reviewer_completeness`, and `approval_gate`. Legacy DRAFT
Golden files remain readable.

## Privacy and build identity

Generic UI, validation and synthetic tests belong in Git. Customer DXF files,
rendered source assets, generated proposal exports and human review results do
not. Every generated package records the automatic repository build identity,
the source SHA-256 and the runtime frame ID.

No merge, deployment, or modification to the canonical reconstruction engine
is part of this workflow.
