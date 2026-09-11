# Output artifact retention

A generated CAD artifact is marked ready only after exact-file validation and
successful durable retention. S3/R2 is preferred when configured and reachable.
When object storage is not configured, the validated bytes, digest, filename,
media type, project identity and revision identity are stored in the shared
application database. This makes the download available from every web/worker
instance. A local-volume helper remains available for single-instance use but
is not treated as shared storage in a multi-instance deployment.

Transient CAD workspaces are removed after either retention path succeeds. A
database artifact is never removed by that cleanup. If both object storage and
the shared database transaction fail, the project remains failed and exposes no
download. Existing download authorization and project ownership checks apply to
both storage paths.
