# Output artifact retention

A generated CAD artifact is marked ready only after exact-file validation and
successful durable retention. S3/R2 is preferred when configured and reachable.
When object storage is not configured, the same validated artifact is copied
atomically to the configured application data volume under the project/revision
identity and reopened before the revision is committed ready.

Transient CAD workspaces are removed after either retention path succeeds. A
local-volume artifact is never removed by that cleanup. If both object storage
and validated local retention fail, the project remains failed and exposes no
download. Existing download authorization and project ownership checks apply to
both storage paths.
