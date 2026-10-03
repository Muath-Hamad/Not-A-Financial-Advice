"""The audit log (docs/08 §7.3, §9): every change to controls.json and
halt.json from git (the commit IS the audit event), merged with the
console's own records — attempts that were not applied, immediate commands —
and the broker command records in ledger/commands.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .ledger import git
from .payloads import ET, parse_utc, wd_label

FILES = ("NASDAQ/live/controls.json", "NASDAQ/live/ledger/halt.json")
SEP = "\x1e"


def _trailers(body: str) -> dict:
    out = {}
    for line in body.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            if k.strip() in ("Actor", "Reason", "Effective", "Console-Action-Id"):
                out[k.strip()] = v.strip()
    return out


def _show(repo: Path, sha: str, rel: str) -> dict | None:
    raw = git(repo, "show", f"{sha}:{rel}")
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None


def _diff(before: dict | None, after: dict | None) -> str:
    before, after = before or {}, after or {}
    parts = []
    for k in sorted(set(before) | set(after)):
        if k == "note":
            continue
        a, b = before.get(k), after.get(k)
        if a == b:
            continue
        if isinstance(a, list) or isinstance(b, list):
            a, b = a or [], b or []
            if all(isinstance(x, str) for x in a + b):
                plus, minus = sorted(set(b) - set(a)), sorted(set(a) - set(b))
                bits = ([f"+{len(plus)} ({', '.join(plus[:4])}{'…' if len(plus) > 4 else ''})"] if plus else []) + \
                       ([f"−{len(minus)} ({', '.join(minus[:4])})"] if minus else [])
                parts.append(f"{k}: " + " ".join(bits))
            else:
                parts.append(f"{k}: {len(a)} → {len(b)}")
        else:
            parts.append(f"{k}: {json.dumps(a)} → {json.dumps(b)}")
    return " · ".join(parts) or "—"


def _norm(repo: Path, doc: dict | None) -> dict | None:
    """Fill controls v2 defaults, so a schema upgrade is not shown as a change."""
    if doc is None:
        return None
    import sys
    live = str(repo / "NASDAQ" / "live")
    if live not in sys.path:
        sys.path.insert(0, live)
    try:
        import controls_schema
        return controls_schema.normalize(doc)
    except ImportError:
        return doc


def _when(iso_utc: str | None) -> str:
    t = parse_utc(iso_utc)
    if not t:
        return "—"
    e = t.astimezone(ET)
    return wd_label(e.date().isoformat()) + " " + e.strftime("%H:%M")


def entries(repo: Path, ledger: Path, store) -> list[dict]:
    out: list[dict] = []
    seen_ids = set()
    log = git(repo, "log", "-n", "200", f"--format={SEP}%H%x1f%cI%x1f%an%x1f%s%x1f%b", "--", *FILES)
    for chunk in (log or "").split(SEP):
        if not chunk.strip():
            continue
        sha, when, author, subject, body = (chunk.split("\x1f", 4) + [""] * 5)[:5]
        tr = _trailers(body)
        changed = git(repo, "show", "--name-only", "--format=", sha) or ""
        rel = next((f for f in FILES if f in changed), FILES[0])
        before, after = _show(repo, sha + "~1", rel), _show(repo, sha, rel)
        if rel.endswith("controls.json"):
            before, after = _norm(repo, before), _norm(repo, after)
        before_after = _diff(before, after)
        aid = tr.get("Console-Action-Id")
        if aid:
            seen_ids.add(aid)
        out.append({
            "t": _when(when), "at": when, "actor": tr.get("Actor") or ("rescreen" if "re-screen" in subject or "rescreen" in subject else "git: " + author.split(" ")[0]),
            "act": subject.replace("control: ", "").strip()[:80], "ba": before_after, "reason": tr.get("Reason") or "—",
            "eff": tr.get("Effective") or "—", "sha": sha[:7], "res": "Applied",
        })
    for ev in store.control_events():
        if ev["id"] in seen_ids:
            continue  # the git commit above is the record
        dry = str(ev.get("sha") or "").startswith("dry-")
        out.append({"t": _when(ev["at_utc"]), "at": ev["at_utc"], "actor": ev["actor"], "act": ev["action"], "ba": ev["before_after"],
                    "reason": ev["reason"], "eff": ev["effective"], "sha": "—" if dry else (ev["sha"] or "—")[:7],
                    "res": ("Applied (dry run)" if dry else "Applied") if ev["applied"] else "Not applied"})
    for f in sorted((ledger / "commands").glob("*.json"), reverse=True)[:50]:
        try:
            rec = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        out.append({"t": _when(rec.get("ts_utc")), "at": rec.get("ts_utc"), "actor": rec.get("actor", "—"), "act": "Broker " + str(rec.get("action")),
                    "ba": f"mode {rec.get('mode')} · {rec.get('status')}", "reason": rec.get("reason", "—"), "eff": "Immediate",
                    "sha": "—", "res": "Applied" if rec.get("status") == "ok" else "Not applied"})
    def utc(v):
        t = parse_utc(v)
        return t.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds") if t else ""
    out.sort(key=lambda r: utc(r.get("at")), reverse=True)
    return out


def pending_changes(repo: Path, cycles: dict) -> list[dict]:
    """Control commits newer than the last cycle record: committed, not yet read."""
    last = max((r.get("ts_utc") or "" for r in cycles.values()), default="")
    out = []
    log = git(repo, "log", "-n", "20", f"--format={SEP}%H%x1f%cI%x1f%s%x1f%b", "--", FILES[0])
    for chunk in (log or "").split(SEP):
        if not chunk.strip():
            continue
        sha, when, subject, body = (chunk.split("\x1f", 3) + [""] * 4)[:4]
        t = parse_utc(when)
        if last and t and t.isoformat() <= (parse_utc(last) or t).isoformat():
            break
        tr = _trailers(body)
        out.append({"what": subject.replace("control: ", ""), "eff": tr.get("Effective", "next cycle"), "sha": sha[:7], "when": _when(when)})
    return out
