---
name: secret-scan
description: Finds API keys, tokens, passwords and private keys in files and in a repository's entire git history, and walks through removing them properly (revoke first, then clean history). Use before pushing, before making a repository public, before publishing a site or package, when a key may have leaked, or when cleaning up old code.
license: GPL-2.0-only
---

# Find and remove secrets

Removing a key from the latest commit does not remove it: it stays in every older commit, in forks, and on
GitHub by commit ID even after a history rewrite. **The only real fix for a leaked key is to revoke it.**

## 1. Scan

```bash
python3 scripts/find_secrets.py .                      # files now
python3 scripts/find_secrets.py --history .            # every line ever committed, all branches
```

"secret" = a provider's published key format (Google, AWS, GitHub, Anthropic, OpenAI, OpenRouter, Slack,
Stripe, Hugging Face, GitLab, npm, private key blocks). "possible" = heuristics (password-like assignments,
credentials in URLs, long hex keys in URLs) that need a look. Output is masked; never print a full secret
into a log, chat or commit message.

## 2. If something is found

1. **Revoke or rotate** the key at its provider. Do this first, even if the repository is private.
2. Move the value out of code: environment variable or a git-ignored file, plus a placeholder in code.
3. Clean history only if the repository is or will be shared: rewrite with `git filter-repo --replace-text`
   (or `git filter-branch --tree-filter` if filter-repo is missing), then delete the rewrite's backup refs
   (`refs/original/`), re-scan with `--history`, and force-push every branch and tag. A force-push is
   destructive: confirm with the owner first.
4. On GitHub, old commits stay reachable by ID after the rewrite. Ask GitHub Support to remove cached views,
   and treat the key as public until it is revoked.

## 3. Prevent

Add the scan to a pre-commit or pre-push hook, or to CI. Keep a `.gitignore` entry for env files.
