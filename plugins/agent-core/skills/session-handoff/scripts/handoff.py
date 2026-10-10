#!/usr/bin/env python3
"""Write or read a HANDOFF.md so another session, another model or a person can resume work exactly.

  handoff.py write [--dir DIR] --task "..." [--done "..."] [--next "..."] [--blocked "..."] [--notes "..."]
      Records the task plus the repository state that the next session needs: branch, HEAD, uncommitted
      and untracked files, unpushed commits and the stash. Repeat --done/--next/--blocked for several items.
  handoff.py read [--dir DIR] [--json]
      Prints the handoff and checks it against the repository now: HEAD moved, branch changed, new or
      vanished uncommitted files. Exit 1 if the state drifted (re-check before trusting the notes).

Exit codes: 0 ok, 1 no handoff found or state drifted, 2 bad usage. Python stdlib and git only.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

NAME = "HANDOFF.md"
STATE_RE = re.compile(r"<!-- handoff-state (\{.*?\}) -->", re.S)


def git(d, *args):
    p = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else None


def repo_state(d):
    top = git(d, "rev-parse", "--show-toplevel")
    if not top:
        return {"git": False}
    status = "\n".join(l for l in (git(d, "status", "--porcelain=v1") or "").splitlines()
                        if not l.endswith(NAME))
    return {
        "git": True,
        "top": top,
        "branch": git(d, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": git(d, "rev-parse", "HEAD"),
        "changed": sorted(l[3:] for l in status.splitlines() if not l.startswith("??")),
        "untracked": sorted(l[3:] for l in status.splitlines() if l.startswith("??")),
        "unpushed": (git(d, "log", "--oneline", "@{upstream}..HEAD") or "").splitlines(),
        "stash": len((git(d, "stash", "list") or "").splitlines()),
        "recent": (git(d, "log", "--oneline", "-5") or "").splitlines(),
    }


def bullets(items, empty="(none)"):
    return "\n".join(f"- {i}" for i in items) if items else empty


def write(a):
    d = Path(a.dir)
    st = repo_state(d)
    now = datetime.now().astimezone().isoformat(timespec="minutes")
    parts = [f"# Handoff ({now})", "", "## Task", a.task, "", "## Done", bullets(a.done),
             "", "## Next steps (in order)", bullets(a.next), "", "## Blocked / needs a human", bullets(a.blocked)]
    if a.notes:
        parts += ["", "## Notes", a.notes]
    if st["git"]:
        parts += ["", "## Repository state when written",
                  f"- branch `{st['branch']}` at `{st['head'][:10]}`",
                  f"- uncommitted: {', '.join(st['changed']) or 'none'}",
                  f"- untracked: {', '.join(st['untracked'][:20]) or 'none'}",
                  f"- unpushed commits: {len(st['unpushed'])}", f"- stash entries: {st['stash']}",
                  "- recent commits:", bullets(st["recent"])]
    parts += ["", "## For the next session",
              "Run `handoff.py read` first: it says whether the repository moved since this was written. "
              "Re-read any file before editing it. Do the first unchecked next step; ask before anything listed "
              "under Blocked.", "", f"<!-- handoff-state {json.dumps({'written': now, **st})} -->", ""]
    out = d / NAME
    out.write_text("\n".join(parts))
    print(f"wrote {out}")
    return 0


def read(a):
    f = Path(a.dir) / NAME
    if not f.is_file():
        print(f"no {NAME} in {a.dir}", file=sys.stderr)
        return 1
    text = f.read_text()
    m = STATE_RE.search(text)
    then = json.loads(m.group(1)) if m else {"git": False}
    now = repo_state(a.dir)
    drift = []
    if then.get("git") and now.get("git"):
        if then["branch"] != now["branch"]:
            drift.append(f"branch changed: {then['branch']} -> {now['branch']}")
        if then["head"] != now["head"]:
            n = git(a.dir, "rev-list", "--count", f"{then['head']}..HEAD")
            drift.append(f"HEAD moved: {then['head'][:10]} -> {now['head'][:10]}"
                         + (f" ({n} new commits)" if n else " (not a descendant: history rewritten or reset)"))
        for label, key in (("uncommitted", "changed"), ("untracked", "untracked")):
            new = sorted(set(now[key]) - set(then[key]))
            gone = sorted(set(then[key]) - set(now[key]))
            if new:
                drift.append(f"new {label} files: {', '.join(new[:10])}")
            if gone:
                drift.append(f"{label} files no longer pending: {', '.join(gone[:10])}")
    if a.json:
        print(json.dumps({"file": str(f), "written": then.get("written"), "drift": drift,
                          "text": STATE_RE.sub("", text).strip()}, indent=2))
    else:
        print(STATE_RE.sub("", text).strip())
        print("\n## Drift check")
        print(bullets(drift, "No drift: the repository is as the handoff describes."))
    return 1 if drift else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write")
    w.add_argument("--dir", default=".")
    w.add_argument("--task", required=True)
    for k in ("done", "next", "blocked"):
        w.add_argument(f"--{k}", action="append", default=[])
    w.add_argument("--notes")
    r = sub.add_parser("read")
    r.add_argument("--dir", default=".")
    r.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not Path(a.dir).is_dir():
        print(f"not a directory: {a.dir}", file=sys.stderr)
        return 2
    return write(a) if a.cmd == "write" else read(a)


if __name__ == "__main__":
    sys.exit(main())
