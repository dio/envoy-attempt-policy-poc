#!/usr/bin/env python3
"""Prepare the pinned Envoy checkout and apply only this PoC's source overlay."""

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build/envoy"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=SOURCE).decode().strip()


def main():
    revision = (ROOT / "envoy-revision.txt").read_text().strip()
    patch = ROOT / "patches/attempt-policy-poc.patch"
    expected_hash = (ROOT / "patches/attempt-policy-poc.sha256").read_text().split()[0]
    if hashlib.sha256(patch.read_bytes()).hexdigest() != expected_hash:
        raise SystemExit("patch digest mismatch; review the patch before updating its recorded digest")
    if not SOURCE.exists():
        SOURCE.mkdir(parents=True)
        git("init")
        git("remote", "add", "origin", "https://github.com/envoyproxy/envoy.git")
        git("fetch", "--depth=1", "origin", revision)
        git("checkout", "--detach", "FETCH_HEAD")
    if git("rev-parse", "HEAD") != revision:
        raise SystemExit("build/envoy has a different revision; use a fresh directory")

    changes = subprocess.check_output(
        ["git", "diff", "--no-color", "--no-ext-diff", "--binary"], cwd=SOURCE)
    if changes != patch.read_bytes():
        if git("status", "--porcelain"):
            raise SystemExit("build/envoy contains other edits; refusing to overwrite them")
        git("apply", "--check", str(patch))
        git("apply", str(patch))
        git("add", "-N", "source/common/router/attempt_policy.h")
        changes = subprocess.check_output(
            ["git", "diff", "--no-color", "--no-ext-diff", "--binary"], cwd=SOURCE)
        if changes != patch.read_bytes():
            raise SystemExit("applied source differs from the recorded patch")
    if git("diff", "--cached", "--name-only"):
        raise SystemExit("unexpected staged changes in build/envoy")
    print(json.dumps({"revision": revision, "patch_sha256": expected_hash, "source": str(SOURCE)}, indent=2))


if __name__ == "__main__":
    main()
