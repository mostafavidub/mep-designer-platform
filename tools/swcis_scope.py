"""Resolve exactly one governing CR, including a sealed cumulative integration."""
from __future__ import annotations
import argparse
import json
import re
import subprocess
from pathlib import Path


def resolve_request(base, head="HEAD", root=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.PIPE).strip()
    def fail(message):
        raise ValueError(message)
    requests = git("diff", "--name-only", f"{base}...{head}", "--", "changes/*.yaml").splitlines()
    if len(requests) == 1:
        return requests[0]
    candidates = []
    for path in requests:
        try:
            body = json.loads((root / path).read_text())
        except (OSError, ValueError):
            fail("UNREADABLE_CHANGE_REQUEST")
        if "integration" in body:
            candidates.append((path, body["integration"]))
    if len(candidates) != 1:
        fail("EXACTLY_ONE_GOVERNING_REQUEST_REQUIRED")
    path, manifest = candidates[0]
    if not isinstance(manifest, dict):
        fail("INVALID_INTEGRATION_MANIFEST")
    baseline, source = manifest.get("base_sha", ""), manifest.get("source_sha", "")
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (baseline, source)):
        fail("EXACT_INTEGRATION_COMMITS_REQUIRED")
    if git("rev-parse", base) != baseline:
        fail("INTEGRATION_BASE_CHANGED")
    if git("merge-base", baseline, source) != baseline or git("merge-base", source, head) != source:
        fail("INTEGRATION_ANCESTRY_INVALID")
    if git("rev-parse", f"{source}^{{tree}}") != manifest.get("source_tree"):
        fail("INTEGRATION_SOURCE_TREE_CHANGED")
    historical = manifest.get("historical_requests")
    expected = git("diff", "--name-only", baseline, source, "--", "changes/*.yaml").splitlines()
    if not isinstance(historical, dict) or not expected or set(historical) != set(expected):
        fail("INTEGRATION_HISTORY_INCOMPLETE")
    if set(requests) != set(expected) | {path} or path in expected:
        fail("UNDECLARED_INTEGRATION_REQUEST")
    for old in expected:
        blob = git("rev-parse", f"{source}:{old}")
        if historical[old] != blob or git("hash-object", old) != blob or git("rev-parse", f"{head}:{old}") != blob:
            fail("HISTORICAL_REQUEST_MUTATED")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    args = parser.parse_args()
    try:
        print(resolve_request(args.base))
    except (ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"SWCIS scope failed: {exc}\n")


if __name__ == "__main__":
    main()
