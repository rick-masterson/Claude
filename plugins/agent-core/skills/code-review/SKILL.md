---
name: code-review
description: Reviews a diff, branch, pull request or file for correctness bugs first, then security, data loss, performance and maintainability, and reports verified findings ranked by severity with a concrete failure scenario for each. Use when asked to review code or a PR, before merging, or to check one's own changes before committing.
license: GPL-2.0-only
---

# Review for bugs that matter

## 1. Understand the change

Read the description or task, then the whole diff (`git diff <base>...HEAD`). For each changed function,
read its callers and the code it calls; bugs live at the boundaries.

## 2. Look, in this order

1. **Correctness:** wrong logic, off-by-one, unhandled empty/null/error cases, wrong types or units,
   race conditions, broken invariants, behaviour changed for existing callers.
2. **Security:** untrusted input reaching a shell, SQL, file path, HTML or deserializer; missing auth
   checks; secrets in code or logs; over-broad permissions.
3. **Data loss and irreversibility:** deletes, migrations, overwrites without backups or transactions.
4. **Performance:** work inside loops that could be done once, unbounded growth, N+1 queries.
5. **Maintainability:** duplicated logic that already exists elsewhere, dead code, misleading names,
   missing tests for the new behaviour.

## 3. Verify before reporting

For each candidate, construct a concrete input or state that triggers it, and check it against the code
(or run it). Drop anything you cannot make concrete. A short list of real bugs beats a long list of maybes.

## 4. Report

Most severe first. Each finding: `file:line`, one-sentence defect, the failure scenario
("given X, Y happens instead of Z"), and the smallest fix. Style preferences go last or not at all.
If nothing survived verification, say so plainly.
