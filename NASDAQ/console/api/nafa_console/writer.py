"""Where control changes are written (docs/08 §3.2, §7.3).

* GitWriter — a local clone (the container's /data/repo, or the Unraid box's
  ledger): pull, write, commit with the structured audit message, push. A
  rejected push undoes the local commit and reports a conflict, so the
  service re-validates against the new state; it never overwrites.
* GitHubWriter — the GitHub contents API: PUT with the blob sha the preview
  was based on (optimistic concurrency); a 409/422 is a conflict.
* DryWriter — local development: nothing is written; the change is recorded
  in the console's own audit table only. The default outside the container.

Workflow dispatches (re-run a cycle, release a held night, the live-control
command) go through the GitHub Actions API when a token is configured.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


class Conflict(Exception):
    """The file changed since the preview; re-read and re-validate."""


class WriteError(Exception):
    pass


def blob_version(text: str | None) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


class DryWriter:
    kind = "dry"

    def __init__(self, repo_root: Path):
        self.root = repo_root

    def read(self, rel: str) -> str | None:
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.exists() else None

    def commit(self, files: dict[str, str], message: str, base: dict[str, str]) -> str:
        for rel, ver in base.items():
            if blob_version(self.read(rel)) != ver:
                raise Conflict(rel)
        return "dry-" + hashlib.sha1(message.encode()).hexdigest()[:7]

    def push_label(self) -> str:
        return "Dry run (CONSOLE_WRITE=dry): nothing was committed or pushed"


class GitWriter:
    kind = "git"

    def __init__(self, repo_root: Path, push: bool = True, branch: str | None = None):
        self.root = repo_root
        self.push = push
        self.branch = branch

    def _git(self, *args: str, check: bool = True) -> str:
        r = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, timeout=60)
        if check and r.returncode != 0:
            raise WriteError(f"git {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:300]}")
        return r.stdout.strip()

    def read(self, rel: str) -> str | None:
        p = self.root / rel
        return p.read_text(encoding="utf-8") if p.exists() else None

    def commit(self, files: dict[str, str], message: str, base: dict[str, str]) -> str:
        if self.push:
            self._git("pull", "--ff-only", "--quiet")
        for rel, ver in base.items():
            if blob_version(self.read(rel)) != ver:
                raise Conflict(rel)
        for rel, text in files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            self._git("add", "--", rel)
        self._git("-c", "user.name=nafa-console", "-c", "user.email=console@nafa.local", "commit", "--quiet", "-m", message)
        sha = self._git("rev-parse", "HEAD")
        if self.push:
            r = subprocess.run(["git", "-C", str(self.root), "push", "--quiet"], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                self._git("reset", "--hard", "--quiet", "HEAD~1")
                self._git("pull", "--ff-only", "--quiet", check=False)
                raise Conflict("push rejected: " + (r.stderr or "").strip()[:200])
        return sha

    def push_label(self) -> str:
        return "Pushed · read by the next step" if self.push else "Committed locally (push disabled)"


class GitHubWriter:
    kind = "github"

    def __init__(self, token: str, repo: str, branch: str = "main", api: str = "https://api.github.com"):
        self.token, self.repo, self.branch, self.api = token, repo, branch, api
        self._sha: dict[str, str] = {}

    def _req(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(f"{self.api}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nafa-console"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            if e.code in (409, 422) and method == "PUT":
                raise Conflict(f"GitHub {e.code}") from e
            if e.code == 404 and method == "GET":
                return None
            raise WriteError(f"GitHub {method} {path}: HTTP {e.code} {e.read()[:200]!r}") from e

    def read(self, rel: str) -> str | None:
        d = self._req("GET", f"/repos/{self.repo}/contents/{rel}?ref={self.branch}")
        if not d:
            self._sha.pop(rel, None)
            return None
        self._sha[rel] = d["sha"]
        return base64.b64decode(d["content"]).decode("utf-8")

    def commit(self, files: dict[str, str], message: str, base: dict[str, str]) -> str:
        sha = ""
        for rel, text in files.items():
            if blob_version(self.read(rel)) != base.get(rel, blob_version(None)):
                raise Conflict(rel)
            body = {"message": message, "content": base64.b64encode(text.encode()).decode(), "branch": self.branch}
            if rel in self._sha:
                body["sha"] = self._sha[rel]
            res = self._req("PUT", f"/repos/{self.repo}/contents/{rel}", body)
            sha = res["commit"]["sha"]
        return sha

    def push_label(self) -> str:
        return f"Committed to {self.branch} on GitHub · read by the next step"


class Dispatcher:
    """GitHub Actions workflow_dispatch (re-runs, release, live-control)."""

    def __init__(self, token: str | None, repo: str | None, branch: str = "main", api: str = "https://api.github.com"):
        self.token, self.repo, self.branch, self.api = token, repo, branch, api

    @property
    def configured(self) -> bool:
        return bool(self.token and self.repo)

    def dispatch(self, workflow: str, inputs: dict | None = None) -> None:
        if not self.configured:
            raise WriteError("workflow dispatch is not configured (CONSOLE_GH_TOKEN / CONSOLE_GH_REPO)")
        body = json.dumps({"ref": self.branch, "inputs": {k: str(v) for k, v in (inputs or {}).items()}}).encode()
        req = urllib.request.Request(f"{self.api}/repos/{self.repo}/actions/workflows/{workflow}/dispatches", method="POST", data=body,
                                     headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json", "User-Agent": "nafa-console"})
        try:
            with urllib.request.urlopen(req, timeout=20):
                pass
        except urllib.error.HTTPError as e:
            raise WriteError(f"dispatch {workflow}: HTTP {e.code}") from e


def make_writer(repo_root: Path):
    mode = os.environ.get("CONSOLE_WRITE", "dry")
    if mode == "git":
        return GitWriter(repo_root, push=os.environ.get("CONSOLE_GIT_PUSH", "1") == "1")
    if mode == "github":
        return GitHubWriter(os.environ["CONSOLE_GH_TOKEN"], os.environ["CONSOLE_GH_REPO"], os.environ.get("CONSOLE_GH_BRANCH", "main"))
    return DryWriter(repo_root)


def make_dispatcher() -> Dispatcher:
    return Dispatcher(os.environ.get("CONSOLE_GH_TOKEN"), os.environ.get("CONSOLE_GH_REPO"), os.environ.get("CONSOLE_GH_BRANCH", "main"))
