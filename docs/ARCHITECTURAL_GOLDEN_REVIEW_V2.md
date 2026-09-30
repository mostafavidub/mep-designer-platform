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
   Spaces are presented as human-readable `فضای 1`, `فضای 2`, and so on;
   selecting one focuses its complete polygon, dims unrelated proposals and
   retains whole-floor position in a minimap. Runtime IDs remain technical
   details rather than reviewer-facing names. The selected label is a bounded
   CSS-pixel HTML badge in screen space, so focusing a tiny polygon cannot make
   the number obscure the plan.
3. Physical geometry and functional semantics are separate decisions. Exact
   source labels and cached semantic evidence are supporting context only;
   unknown function never prevents review of a physical boundary.
4. Geometry can be edited with explicit undo/redo. Missing spaces, voids and
   portals can be drawn from the raw source.
5. Source-only completeness hides proposal and accepted overlays. The annotator
   must inspect all nine floor sectors and answer every omission question.
6. A different reviewer repeats a source-only pass before viewing the final
   overlay. Annotator and reviewer identities must differ.
7. Geometric adjacency and access connectivity are regenerated from accepted
   geometry. Windows cannot create access edges.
8. Approval fails closed while any proposal, critical issue, sector, required
   question, identity or geometry check is incomplete. Official benchmark
   scoring remains disabled for every status except `APPROVED`.

Rejected Physical Space proposals retain their original geometry and audit
identity with a separate `rejection_class` such as `COLUMN`,
`WALL_OR_WALL_MASS`, or `GRID_OR_AXIS`. A rejection class is never written into
the functional category of an accepted Physical Space. Legacy DRAFT files may
temporarily omit it; approval requires it for every rejected space.

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
