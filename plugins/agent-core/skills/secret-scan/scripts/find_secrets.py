#!/usr/bin/env python3
"""Find API keys, tokens and private keys in files and in git history, before code is pushed or published.

  find_secrets.py PATH [PATH ...]      scan files and folders (skips .git, binaries and files over 2 MB)
  find_secrets.py --history REPO       scan every line ever added in any commit on any branch
  add --json for machine output. Matches are shown masked (first 4 and last 2 characters).

Exit codes: 0 nothing found, 1 secrets found, 2 bad usage.
High-confidence patterns are reported as "secret"; heuristic ones ("possible") need a human look.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    # (kind, confidence, regex) — provider formats are from each provider's published token format.
    ("private-key", "secret", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"),
    ("google-api-key", "secret", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("aws-access-key-id", "secret", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("github-token", "secret", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"),
    ("anthropic-key", "secret", r"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    ("openrouter-key", "secret", r"\bsk-or-v1-[0-9a-f]{64}\b"),
    ("openai-key", "secret", r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}T3BlbkFJ[A-Za-z0-9_\-]{20,}"),
    ("slack-token", "secret", r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    ("stripe-live-key", "secret", r"\b(?:sk|rk)_live_[0-9A-Za-z]{24,}\b"),
    ("huggingface-token", "secret", r"\bhf_[A-Za-z0-9]{34}\b"),
    ("gitlab-token", "secret", r"\bglpat-[A-Za-z0-9_\-]{20}\b"),
    ("npm-token", "secret", r"\bnpm_[A-Za-z0-9]{36}\b"),
    ("url-credentials", "possible", r"\b[a-z][a-z0-9+.-]*://[^/\s:@'\"]+:[^/\s@'\"]{6,}@[^\s'\"]+"),
    ("assigned-secret", "possible",
     r"(?i)\b(?:api[_-]?key|apikey|secret|token|passw(?:or)?d|auth)\w*\s*[:=]\s*['\"]([^'\"\s]{12,})['\"]"),
    ("hex-key-in-url", "possible", r"(?i)(?:key|token|forecast|secret)[=/]([0-9a-f]{32,64})\b"),
]
COMPILED = [(k, c, re.compile(rx)) for k, c, rx in PATTERNS]
PLACEHOLDER = re.compile(r"(?i)(x{6,}|\*{4,}|<[^>]+>|\$\{?[A-Z_]+\}?|your[_-]?|example|changeme|dummy|placeholder|"
                         r"redacted|removed|fake|test[_-]?key|0{8,}|1234567)")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".mypy_cache"}
MAX_BYTES = 2_000_000


def mask(s):
    return s[:4] + "…" + s[-2:] if len(s) > 8 else "…"


def scan_line(line):
    hits = []
    for kind, conf, rx in COMPILED:
        for m in rx.finditer(line):
            val = m.group(1) if m.groups() and m.group(1) else m.group(0)
            if conf == "possible" and PLACEHOLDER.search(val):
                continue
            if kind == "private-key":
                val = "PRIVATE KEY"
            hits.append((kind, conf, val))
    if any(c == "secret" for _, c, _ in hits):
        hits = [h for h in hits if h[1] == "secret"]  # a confident match makes the heuristics redundant
    return hits


def scan_paths(paths):
    found = []
    for root in paths:
        root = Path(root)
        files = [root] if root.is_file() else (p for p in root.rglob("*") if p.is_file())
        for p in files:
            if SKIP_DIRS & set(p.parts) or p.is_symlink() or p.stat().st_size > MAX_BYTES:
                continue
            data = p.read_bytes()
            if b"\0" in data[:4096]:
                continue
            for n, line in enumerate(data.decode(errors="replace").splitlines(), 1):
                for kind, conf, val in scan_line(line):
                    found.append({"kind": kind, "confidence": conf, "file": str(p), "line": n,
                                  "match": mask(val), "commit": None})
    return found


def scan_history(repo):
    proc = subprocess.run(["git", "-C", repo, "log", "--all", "-p", "--no-color", "--no-ext-diff", "-U0",
                           "--format=commit %H"], capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"git log failed: {proc.stderr.strip()}")
    found, seen, commit, path = [], set(), None, None
    for line in proc.stdout.splitlines():
        if line.startswith("commit "):
            commit = line[7:]
        elif line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            for kind, conf, val in scan_line(line[1:]):
                key = (kind, val, path)
                if key in seen:
                    continue  # report each secret once per file: at its newest commit (git log is newest first)
                seen.add(key)
                found.append({"kind": kind, "confidence": conf, "file": path, "line": None,
                              "match": mask(val), "commit": commit})
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--history", metavar="REPO")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not a.paths and not a.history:
        ap.print_usage(sys.stderr)
        return 2
    for p in a.paths:
        if not Path(p).exists():
            print(f"no such path: {p}", file=sys.stderr)
            return 2
    found = scan_paths(a.paths) if a.paths else []
    if a.history:
        found += scan_history(a.history)
    if a.json:
        print(json.dumps(found, indent=2))
    else:
        for f in found:
            where = f"{f['file']}:{f['line']}" if f["line"] else f"{f['file']} @ {f['commit'][:10]}"
            print(f"{f['confidence']:8} {f['kind']:20} {where}  {f['match']}")
        sure = sum(f["confidence"] == "secret" for f in found)
        print(f"\n{sure} secret, {len(found) - sure} possible")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
