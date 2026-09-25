---
name: multi-session-git
description: Commit, branch and merge safely when more than one agent session (or a person) works in the same git repository or checkout at once. Use before any commit in a shared repo, when git status shows changes you did not make, when files change under you mid-task, when setting up parallel work, or when asked to "use a worktree".
---

# Several sessions, one repository

Two sessions editing one checkout will eventually commit each other's half-finished work, or lose it. Most
commands that feel harmless (`git add -A`, `git commit -a`, `git stash pop`, `git checkout .`) act on
*everything* in the working tree, including files someone else is editing right now.

## 1. Before every commit: preflight

```bash
python3 scripts/git_preflight.py --mine path/you/changed.py other/file.md [--json]
```

- **Errors** (exit 1): something is staged that isn't yours, or the branch is behind its upstream.
- **Warnings:** changed files that aren't yours (leave them), files modified in the last 15 minutes that aren't
  yours (**another session is editing now**), and the same branch checked out elsewhere.
- **Info:** every worktree, and the stash, which is shared by all of them.
- It ends by printing the exact `git add` for your files.

## 2. Rules

- **Stage explicit paths only.** `git add path/a path/b`, never `git add -A`, `git add .` or `git commit -a`.
- **Test before committing, and stop on failure:** `run-tests && git commit ...`, not `run-tests; git commit ...`.
  With someone else's edits in the tree, the tests may fail for reasons that aren't yours. Report that; don't "fix"
  their files.
- **Never revert, reformat or "clean up" files you didn't change**, even if they look broken. They are probably
  mid-edit.
- **The stash is shared between worktrees.** Don't use bare `git stash` / `git stash pop`. To set work aside, make
  a WIP commit on your own branch.
- **Files changing under you mid-task** (the harness reports "modified since read", or `git status` shows new
  changes): assume another session did it. Re-read before editing, and keep your edits to your own lines.

## 3. Parallel work: one worktree per session

```bash
git worktree add -b <topic>/work ../<repo>-<topic> <base-commit>
```

- Name the folder after the topic (`repo-mcp`, `repo-branding`) and put the branch under a matching prefix.
- **Gitignored files are not copied into a new worktree:** `.venv`, `.env`, `data/`, local state. Use the main
  checkout's copies by absolute path, or link them. Never commit them.
- If the other session holds the main checkout with uncommitted work, **move yourself** into a new worktree
  instead of moving their changes.
- **Merging back:** once the other session has committed, merge your branch into the main branch. If both touched
  the same file (journals and changelogs are the usual collision), resolve it keeping both entries. List what was
  merged in the commit message.
- **Finishing:** after a merge, remove the worktree (`git worktree remove <path>`) and delete the branch, but only
  with the user's agreement, since it's their record of the work.

## 4. When the harness refuses a command in a worktree

Some agent harnesses confine a worktree session and refuse commands they can't prove stay inside it (complex
pipelines, `cd` elsewhere, `systemctl ... enable`). Split the command into plain single commands, use absolute
paths, and do the same thing another way when needed (for example, enable a user unit by symlinking it into
`default.target.wants/`). Don't try to get around the confinement to act on another checkout; leave the worktree
first.
