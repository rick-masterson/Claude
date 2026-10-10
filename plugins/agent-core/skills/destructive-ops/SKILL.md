---
name: destructive-ops
description: Runs deletions, overwrites, migrations, force-pushes, history rewrites, permission changes and other hard-to-undo operations safely, by inspecting the target, backing up, dry-running and confirming scope first. Use before rm -rf, git reset/clean/push --force, filter-repo, DROP or DELETE, chmod/chown -R, disk partitioning or formatting, mass renames, or any change to production or shared systems.
license: GPL-2.0-only
---

# Look, back up, rehearse, then act

## Before the command

1. **Look at the target.** List exactly what will be affected (`ls`, `git status`, `SELECT count(*) ...
   WHERE <same condition>`, `lsblk`). Check that the path or condition is the one you think it is: no
   empty variables (`rm -rf "$DIR/"` with `DIR` unset), no globs matching more than intended.
2. **Ask whose it is.** Files, branches or data you did not create may belong to someone else or another
   session. Do not delete or "clean up" them.
3. **Back up** what cannot be recreated: copy, `git branch backup/<name>`, `git bundle`, database dump,
   filesystem snapshot. Note where the backup is.
4. **Dry-run** when the tool supports it (`--dry-run`, `-n`, `git clean -n`, a transaction you roll back,
   `rsync --dry-run`).
5. **Confirm** with the owner for anything irreversible or outward-facing: force-pushes, publishing,
   history rewrites, deleting shared data, production changes. Approval for one action does not extend to
   the next one.

## While acting

Use the narrowest form: specific paths, not wildcards; `--force-with-lease`, not `--force`; one step at a
time with a check in between. Prefer moving to a trash folder over deleting.

## After

Verify the result matches the plan (counts, listings, the remote's refs). Report what changed, where the
backup is, and how to undo it. If something unexpected happened, stop and report before continuing.
