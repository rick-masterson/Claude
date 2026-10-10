---
name: verify-before-done
description: Requires fresh evidence before claiming any task is complete, fixed, passing or working, and reporting results exactly as observed. Use before saying "done", "fixed", "tests pass" or "it works", before committing or opening a pull request, and whenever summarizing what was accomplished.
license: GPL-2.0-only
---

# Evidence before claims

A claim of success is only as good as the check behind it, run after the last change.

## Before saying it is done

1. Name the check that would prove it: the test command, the build, the page loading, the API returning
   the right value, the bug's reproduction no longer reproducing.
2. Run it now, after your final edit. A run from before the last change does not count.
3. Read the actual output: exit code, failures, warnings, skipped tests. "0 tests ran" is not a pass.
4. Check the original requirement point by point, not just "no errors".

## Report faithfully

- Say what you ran and what it showed, in one line each.
- Failed: say so, with the relevant output. Do not soften it into "mostly works".
- Not checked: say "not verified" and why (no access, needs a browser, needs credentials).
- Skipped steps, workarounds and assumptions are stated, not buried.
- When the evidence is solid, state the result plainly without hedging.

## Red flags

"Should work now", "probably fixed", "looks good" with no command behind it; tests edited to pass;
error output that was never read; a fix verified only on the happy path.
