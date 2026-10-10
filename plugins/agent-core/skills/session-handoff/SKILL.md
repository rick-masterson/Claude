---
name: session-handoff
description: Writes and reads a HANDOFF.md that lets another session, another model or a person resume a task exactly, with the repository state recorded and a drift check on resume. Use when stopping mid-task, when a usage or context limit is near, when handing work to a different agent, at the end of a long session, or when starting work that a previous session left unfinished.
license: GPL-2.0-only
---

# Hand off work so anyone can resume it

Context windows end, limits hit and sessions crash. Notes in a chat are lost; a file in the repository
is not. Write a handoff whenever you might stop before the task is finished.

## Before stopping

```bash
python3 scripts/handoff.py write --task "what we are trying to achieve" \
  --done "finished item" --next "first next step" --next "second" \
  --blocked "anything that needs a human decision" --notes "gotchas, commands, links"
```

It records the branch, HEAD, uncommitted, untracked and unpushed work, and the stash. Write next steps as
commands or concrete actions, in order. Put every decision that needs a human under `--blocked`.
Commit your finished work first if you are allowed to; do not commit half-done work just to save it.

## When resuming

```bash
python3 scripts/handoff.py read
```

Exit 1 means the repository moved since the handoff (new commits, branch switched, files changed): someone
else worked here. Re-read the affected files before trusting the notes. Then do the first next step, and
update or delete HANDOFF.md when the task is done.

## Rules

- One HANDOFF.md per working directory; overwrite it, don't append forever.
- Never put secrets in it. Decide whether it should be committed or git-ignored for this repository.
- If you cannot run Python, write the same sections by hand: Task, Done, Next steps, Blocked, Notes,
  plus `git status` and `git log -3 --oneline`.
