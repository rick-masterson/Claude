#!/usr/bin/env python3
"""Before committing in a repo that other sessions (agents or people) may also be editing: what else is going on?

    git_preflight.py [--repo DIR] [--mine PATH ...] [--recent-minutes 15] [--json]

--mine lists the paths YOU changed and mean to commit. Without it, the report is informational only.

  E  staged files that are not in --mine: committing now would take someone else's work under your message
  E  the branch is behind its upstream (pull or rebase first, or your push will be rejected or will merge blind)
  W  other modified or untracked files: someone else's work in progress; leave them alone, don't stage them
  W  of those, files modified in the last --recent-minutes: probably ANOTHER SESSION EDITING RIGHT NOW
  W  the same branch is checked out in another worktree
  I  every worktree of this repository and its branch; stash entries (the stash is shared by all worktrees)

Exit 0: safe to commit exactly --mine. 1: an error above. 2: not a git repository or bad usage.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def git(repo: Path, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pre-commit check for repos shared by several sessions.")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--mine", nargs="*", default=None, help="paths you changed and intend to commit")
    ap.add_argument("--recent-minutes", type=float, default=15.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        top = Path(git(args.repo, "rev-parse", "--show-toplevel").strip())
    except RuntimeError as e:
        print(f"{args.repo}: {e}", file=sys.stderr)
        return 2
    mine = None
    if args.mine is not None:
        mine = set()
        for m in args.mine:
            p = Path(m)
            p = p if p.is_absolute() else (Path.cwd() / p)
            try:
                mine.add(str(p.resolve().relative_to(top.resolve())))
            except ValueError:
                mine.add(m)

    issues, info = [], {}
    add = lambda level, msg: issues.append({"level": level, "message": msg})

    branch = git(top, "rev-parse", "--abbrev-ref", "HEAD").strip()
    info["branch"] = branch
    status = git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
    staged, changed, untracked = set(), set(), set()
    i = 0
    while i < len(status):
        entry = status[i]
        if not entry:
            i += 1; continue
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC":
            i += 1  # the rename source follows
        if x == "?":
            untracked.add(path)
        else:
            if x not in " ?":
                staged.add(path)
            if y not in " ?":
                changed.add(path)
        i += 1
    info.update(staged=sorted(staged), unstaged=sorted(changed), untracked=sorted(untracked))

    everything = changed | untracked | staged
    # A --mine entry covers itself and, if it is a directory, everything under it.
    is_mine = lambda p: mine is not None and any(p == m or p.startswith(m.rstrip("/") + "/") for m in mine)
    if mine is not None:
        for p in sorted(x for x in staged if not is_mine(x)):
            add("error", f"staged but not yours: {p} (git restore --staged '{p}')")
        for m in sorted(mine):
            if not any(p == m or p.startswith(m.rstrip("/") + "/") for p in everything):
                add("warning", f"in --mine but git shows no change: {m}")
        others = sorted(p for p in everything if not is_mine(p))
    else:
        others = sorted(everything)

    now = time.time()
    recent = []
    for p in others:
        f = top / p
        try:
            age_min = (now - f.stat().st_mtime) / 60
        except OSError:
            continue
        if age_min <= args.recent_minutes:
            recent.append((p, round(age_min, 1)))
    for p in others:
        if mine is not None:
            add("warning", f"not yours, leave it: {p}")
    for p, age in recent:
        add("warning", f"modified {age} min ago and not yours: {p}: another session is probably editing now")

    try:
        upstream = git(top, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
        subprocess.run(["git", "-C", str(top), "fetch", "-q"], capture_output=True, timeout=30)
        behind, ahead = (int(n) for n in git(top, "rev-list", "--left-right", "--count", f"{upstream}...HEAD").split())
        info.update(upstream=upstream, behind=behind, ahead=ahead)
        if behind:
            add("error", f"{branch} is {behind} commit(s) behind {upstream}: pull/rebase before committing")
    except (RuntimeError, subprocess.TimeoutExpired):
        info["upstream"] = None

    worktrees, cur = [], {}
    for line in git(top, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if cur:
                worktrees.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].removeprefix("refs/heads/")
    info["worktrees"] = worktrees
    for w in worktrees:
        if w.get("branch") == branch and Path(w["path"]).resolve() != top.resolve():
            add("warning", f"{branch} is also checked out in {w['path']}")

    stash = [l for l in git(top, "stash", "list").splitlines() if l.strip()]
    info["stash"] = stash

    errors = [x for x in issues if x["level"] == "error"]
    if args.json:
        print(json.dumps({"repo": str(top), "ok": not errors, "info": info, "issues": issues}, indent=2))
    else:
        print(f"repo {top}  branch {branch}"
              + (f"  (upstream {info['upstream']}: behind {info['behind']}, ahead {info['ahead']})"
                 if info.get("upstream") else "  (no upstream)"))
        for w in worktrees:
            print(f"  worktree {w['path']}  [{w.get('branch', 'detached')}]")
        if stash:
            print(f"  stash: {len(stash)} entr{'y' if len(stash) == 1 else 'ies'} (shared by every worktree; "
                  "never `git stash pop` blind)")
        for x in issues:
            print(f"{x['level'].upper():7} {x['message']}")
        if mine is not None:
            print(("OK: stage exactly: git add " + " ".join(sorted(mine))) if not errors else "FAIL")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
