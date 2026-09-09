# Runtime Contract and Semantic Revision Matrix

The Mechanical product has one living executable runtime. Its executable identity is the Git build identity; semantic revisions below describe schemas, rule books, catalogues and governance contracts only. They do not select parallel Mechanical engines.

| Contract | Canonical identity / revision |
|---|---|
| Mechanical runtime identity | `mechanical` |
| Production CAD entrypoint | `cad_engine.main:app` |
| Executable build | Git commit SHA + content hashes from `cad_engine/build_identity.py` |
| PMM schema | `project-mechanical-model/v3` |
| Traceability policy | `NO_ORPHAN_ENGINEERING_OUTPUT` |
| Mechanical Rule Book | `mechanical-rulebook/5.0` |
| Fixture/equipment Rule Book | `2.4-fixture-equipment-approved-symbols` |
| Mechanical site manifest contract | `12.1` |
| Manufacturer catalogue schema | `manufacturer-catalogue/1` |
| Governance contract | `mechanical-design-governance/1` |

## Runtime policy

There is no Mechanical pipeline version, CAD API release number, Authority vNN, Coordination vNN, or version-selected renderer in the living runtime. `cad_engine.main:app` reaches only canonical semantic module names. Runtime rollback means redeploying an approved Git commit or tag.

Historical `*_vNN.py` sources and historical test names may remain temporarily as compatibility evidence while retirement regression depends on them, but production imports, launchers, workflow identities, status routes and generated artifact identities may not point to them. Their inventory must only decrease.

## Synchronization policy

`cad_engine/runtime_contract.py`, `cad_engine/build_identity.py` and `standards/active-release.json` define the active runtime/build contract. The application Rule Book, deploy-time Rule Book generator, runtime health/status endpoints, launchers and this matrix are checked by the fail-closed **Runtime Contract Synchronization** gate.

The panel must place this exact contract in `_runtime_contract`, use
`_canonical_input_contract` for project engineering evidence, and call only
`cad_engine.main_transport.design` for an in-process CAD request.  A successful
response is accepted only when its build identity, report runtime contract and
unversioned `mechanical` authority are identical to the request.  The retired
`active_version_manifest`, `_v19_input_contract` and versioned design entrypoints
are forbidden on this production transport path.

An architectural title that explicitly declares a typical-floor range is
preserved as one source-backed identity (`TYPICAL_<first>_<last>`) through
topology, riser documentation and target-board materialization. Unknown titles
and detail pseudo-levels remain fail-closed; the runtime never invents separate
floor geometry that the architectural source does not contain.

When detected architectural plan regions are nested, a source point belongs to
the unique smallest containing region (the most-specific source boundary). Equal
minimum regions remain ambiguous and stop generation.

PMM level bounds come from the level profile when present; if that summary omits
them, the exact same-name level in the source-backed architecture model supplies
the already-detected bounds. Non-identical names are never matched.
