# Architecture Input Retention Standard

Active platform release: `18.5.10`

The uploaded architectural DXF or ZIP is a release-critical project source.
Automated cleanup may remove a local copy only after the same project has a
verified durable object-storage copy. A failed, ready, input-required or
retryable status never authorizes deletion of the durable source.

If a legacy project has already lost both copies, the system must stop before
creating another design revision, preserve its answers and analysis, and show
an explicit upload form for the same source file. Blind retries and misleading
generic failure messages are forbidden.
