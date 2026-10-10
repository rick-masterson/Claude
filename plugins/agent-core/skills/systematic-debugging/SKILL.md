---
name: systematic-debugging
description: Finds the root cause of a bug, failing test, crash or unexpected behaviour through reproduction, evidence and one-variable-at-a-time hypotheses before changing code. Use for any error, regression, flaky test, "it worked yesterday", or when a first fix attempt did not work.
license: GPL-2.0-only
---

# Debug from evidence, not guesses

## 1. Reproduce

Get a command that shows the failure every time. Write it down. If it is intermittent, find what changes
between runs (timing, order, data, environment) and record the failure rate.

## 2. Read the evidence

The full error and stack trace, logs around the time of failure, and what changed recently
(`git log`, `git diff`, dependency updates, config, environment). Many bugs are explained by the last change.

## 3. Narrow it down

- Compare a working case with a failing one and list every difference.
- Bisect: in history (`git bisect run <command>`), in input (halve the data), or in code (cut the path in half).
- Form one hypothesis, predict what a test of it will show, then test only that. Change one thing at a time.

## 4. Fix the cause

Fix where the bad state is created, not where it is noticed. Add a test that fails before the fix and
passes after. Run the full suite, not just the new test.

## 5. Stop rules

- Two failed fixes in a row: stop patching. Go back to step 2; the model of the bug is wrong.
- Never delete or weaken a test, catch-and-ignore an error, or add a retry loop to make a symptom go away
  without explaining the cause.
- Explain the root cause in one or two sentences in the commit or report.
