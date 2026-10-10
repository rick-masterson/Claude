#!/usr/bin/env python3
# audit-skill: rule-definitions
"""Static security audit of an agent skill (a folder with SKILL.md) before you install or run it.

Reads files only; never executes anything from the skill. Checks the threats listed in SafeDep's Agent Skills
threat model and the OWASP Agentic Skills Top 10 draft: instructions hidden in the always-loaded description,
invisible Unicode, runtime fetches of remote instructions, secret and environment harvesting, writes to agent
configuration (persistence), pre-approved dangerous tools, unpinned script dependencies, obfuscated payloads.

Usage: audit_skill.py SKILL_DIR [--json]
Exit codes: 0 no findings at warn level or above, 1 findings, 2 bad usage.

A file whose first five lines contain the marker "audit-skill: rule-definitions" (a scanner's own pattern
list) has its pattern matches reported as info, and the opt-out itself is reported as a warning, so the
marker cannot hide anything from a reviewer.
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

TEXT_SUFFIXES = {".md", ".txt", ".py", ".sh", ".bash", ".js", ".mjs", ".ts", ".rb", ".pl", ".ps1", ".yaml",
                 ".yml", ".json", ".toml", ".cfg", ".ini", ""}
MAX_BYTES = 2_000_000

# (id, severity, regex, message). Severity: high = likely malicious or dangerous; warn = needs a human look.
RULES = [
    ("remote-instructions", "high",
     r"\b(fetch|download|curl|wget|load|pull)\b[^\n]{0,60}(instructions?|config|prompt|rules)[^\n]{0,40}https?://",
     "tells the agent to load instructions or config from a URL at run time"),
    ("pipe-to-shell", "high", r"(curl|wget)[^\n|]*\|\s*(ba|z|da)?sh\b", "downloads and pipes straight into a shell"),
    ("env-harvest", "warn",
     r"(os\.environ(\.copy\(\))?\s*\)|os\.environ\.items\(\)|printenv|\benv\s*\||process\.env\s*\)|"
     r"JSON\.stringify\(\s*process\.env)", "reads the whole environment (where API keys live)"),
    ("secret-files", "high",
     r"(\.ssh/id_|\.aws/credentials|\.netrc\b|\.git-credentials|\.config/gh/hosts|\.docker/config\.json|"
     r"\.pypirc|\.gnupg/private-keys|--export-secret-keys|security find-generic-password)", "touches credential files"),
    ("agent-config-write", "warn",
     r"(>>?|write|append|tee|edit|modify|update)[^\n]{0,60}(AGENTS\.md|CLAUDE\.md|GEMINI\.md|\.cursorrules|"
     r"\.claude/settings(\.local)?\.json|\.codex/config|\.gemini/settings|hooks\.json)",
     "writes agent instructions or settings (persists across sessions; fine only if that is the skill's job)"),
    ("exfil-endpoint", "high",
     r"(webhook\.site|requestbin|pipedream\.net|ngrok\.(io|app)|discord(app)?\.com/api/webhooks|"
     r"api\.telegram\.org/bot|pastebin\.com|transfer\.sh)", "sends data to a common exfiltration endpoint"),
    ("obfuscated-exec", "high",
     r"(eval|exec)\s*\(\s*(base64|codecs|bytes\.fromhex|zlib|marshal|atob)|base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh",
     "decodes and executes hidden code"),
    ("ignore-instructions", "high",
     r"(ignore|disregard|override)\s+(all\s+|any\s+)?(previous|prior|above|system|user'?s?)\s+(instructions|rules|prompts?)",
     "classic prompt-injection phrasing"),
    ("conceal", "high",
     r"(do not|don't|never)\s+(tell|inform|mention|show|reveal)[^\n]{0,30}(the\s+)?(user|human|operator)",
     "asks the agent to hide actions from the user"),
    ("dangerous-shell", "warn",
     r"(rm\s+-rf\s+[/~$]|chmod\s+(-R\s+)?777|sudo\s|mkfs|dd\s+if=|:\(\)\s*\{|git\s+push\s+(-f|--force))",
     "destructive or privileged command"),
    ("network-call", "warn",
     r"(requests\.(get|post|put)|urllib\.request|http\.client|fetch\(|axios|curl\s|wget\s|Invoke-WebRequest|socket\.)",
     "makes network calls (check where and what it sends)"),
    ("subprocess", "warn", r"(subprocess\.|os\.system|os\.popen|child_process|execSync|spawnSync)",
     "runs other programs"),
    ("install-at-runtime", "warn", r"(pip|pip3|npm|pnpm|yarn|gem|cargo)\s+(install|add)\b|npx\s+-y|uvx\s",
     "installs packages at run time (supply-chain risk)"),
]

# Rules about what code does: in prose (docs) they are only worth a look; in scripts they are serious.
CODE_RULES = {"pipe-to-shell", "secret-files", "exfil-endpoint", "obfuscated-exec", "dangerous-shell"}
PROSE_SUFFIXES = {".md", ".txt"}
RISKY_CMDS = {"sudo", "rm", "curl", "wget", "ssh", "scp", "bash", "sh", "zsh", "python", "python3", "node", "perl",
              "ruby", "eval", "git", "npx", "dd", "chmod", "chown"}

OPT_OUT = "audit-skill: " + "rule-definitions"  # split so this line is not itself the marker

INVISIBLE = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff", "\u00ad", "\u180e"}


def finding(sev, rule, path, line, msg, text=""):
    return {"severity": sev, "rule": rule, "file": str(path), "line": line, "message": msg, "text": text[:160]}


def split_frontmatter(text):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    return text[3:end], text[end + 4:]


def frontmatter_fields(fm):
    """Tiny YAML subset: top-level 'key: value' plus folded/indented continuation lines."""
    fields, key = {}, None
    for line in fm.splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            fields[key] = m.group(2).strip().strip("\"'")
        elif key and line.startswith((" ", "\t")):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


def check_unicode(rel, text, out):
    for n, line in enumerate(text.splitlines(), 1):
        bad = sorted({c for c in line if c in INVISIBLE or unicodedata.category(c) in ("Cf", "Co")
                      or 0xE0000 <= ord(c) <= 0xE007F})
        if bad:
            names = ", ".join(f"U+{ord(c):04X}" for c in bad)
            out.append(finding("high", "invisible-unicode", rel, n, f"invisible or tag characters ({names})", line))


def check_description(rel, fields, out):
    desc = fields.get("description", "")
    if not desc:
        out.append(finding("warn", "no-description", rel, 1, "missing description (spec requires one)"))
        return
    if len(desc) > 1024:
        out.append(finding("warn", "long-description", rel, 1, f"description is {len(desc)} chars (spec max 1024)"))
    imperative = re.search(r"\b(always|must|never|before (doing|answering|any)|first run|run this|execute|"
                           r"curl|http|ignore)\b", desc, re.I)
    if imperative:
        out.append(finding("warn", "description-instructions", rel, 1,
                           "description contains commands or rules; it is loaded into every session, "
                           "so it should only say what the skill does and when to use it", desc))


def check_allowed_tools(rel, fields, out):
    tools = fields.get("allowed-tools", "")
    if not tools:
        return
    danger, broad = False, bool(re.search(r"\bBash\b(?!\()", tools))
    for inner in re.findall(r"Bash\(([^)]*)\)", tools):
        toks = inner.replace(":*", " *").split()
        if not toks or toks[0] == "*" or toks[0] in ("sudo", "rm", "curl", "wget", "dd", "eval"):
            danger = True
        elif toks[0] in RISKY_CMDS and (len(toks) == 1 or toks[1] == "*"):
            broad = True  # e.g. Bash(python3:*) runs anything; Bash(python3 scripts/x.py *) is scoped
    if danger:
        out.append(finding("high", "pre-approved-tools", rel, 1,
                           "allowed-tools pre-approves dangerous commands without asking", tools))
    elif broad:
        out.append(finding("warn", "pre-approved-tools", rel, 1,
                           "allowed-tools pre-approves any shell or interpreter command", tools))
    else:
        out.append(finding("info", "allowed-tools", rel, 1, "pre-approves tools; check each one", tools))


def check_dependencies(rel, text, out):
    block = re.search(r"# /// script\n(.*?)# ///", text, re.S)
    if block:
        for dep in re.findall(r'"([^"]+)"', block.group(1)):
            if re.match(r"^[A-Za-z0-9_.\-\[\]]+$", dep) and "==" not in dep:
                out.append(finding("warn", "unpinned-dependency", rel, 1,
                                   f"inline script dependency '{dep}' is not pinned (resolved fresh on every run)"))
    if rel.name == "requirements.txt":
        for n, line in enumerate(text.splitlines(), 1):
            line = line.split("#")[0].strip()
            if line and "==" not in line and not line.startswith("-"):
                out.append(finding("warn", "unpinned-dependency", rel, n, f"'{line}' is not pinned"))


def audit(root):
    root = Path(root)
    out = []
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        out.append(finding("high", "no-skill-md", "SKILL.md", 0, "no SKILL.md in this folder"))
        return out
    files = sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)
    for p in files:
        rel = p.relative_to(root)
        if p.is_symlink():
            out.append(finding("high", "symlink", rel, 0, f"symlink to {p.resolve()} (can point outside the skill)"))
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES and p.stat().st_size > 0:
            head = p.read_bytes()[:4]
            if head.startswith(b"\x7fELF") or head[:2] == b"MZ":
                out.append(finding("high", "binary-executable", rel, 0, "ships a compiled executable"))
            continue
        if p.stat().st_size > MAX_BYTES:
            out.append(finding("warn", "large-file", rel, 0, "large text file; not scanned"))
            continue
        text = p.read_text(errors="replace")
        rule_file = OPT_OUT in "\n".join(text.splitlines()[:5])
        if rule_file:
            out.append(finding("warn", "opt-out", rel, 0,
                               "file marks itself as rule definitions; its pattern matches are only info, "
                               "so read it yourself"))
        check_unicode(rel, text, out)
        check_dependencies(rel, text, out)
        if p == skill_md:
            fm, _ = split_frontmatter(text)
            fields = frontmatter_fields(fm or "")
            check_description(rel, fields, out)
            check_allowed_tools(rel, fields, out)
            if fields.get("name") and fields["name"] != root.resolve().name:
                out.append(finding("info", "name-mismatch", rel, 1,
                                   f"name '{fields['name']}' differs from folder '{root.resolve().name}'"))
        prose = p.suffix.lower() in PROSE_SUFFIXES
        for n, line in enumerate(text.splitlines(), 1):
            for rid, sev, rx, msg in RULES:
                m = re.search(rx, line, re.I)
                if not m:
                    continue
                if sev == "high" and prose and rid in CODE_RULES:
                    sev = "warn"
                if rule_file:
                    sev = "info"
                if rid in ("ignore-instructions", "conceal") and re.search(r"[\"\u201c'`]\s*$", line[:m.start()]):
                    sev, msg = "warn", msg + " (quoted, probably an example)"
                out.append(finding(sev, rid, rel, n, msg, line.strip()))
        if not prose and not rule_file and re.search(RULES[2][2], text) and re.search(RULES[10][2], text, re.I):
            out.append(finding("high", "env-exfil", rel, 0,
                               "reads the whole environment and makes network calls in the same file"))
        if re.search(r"[A-Za-z0-9+/]{200,}={0,2}", text):
            out.append(finding("warn", "encoded-blob", rel, 0, "contains a long base64-like blob"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("skill_dir")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not Path(a.skill_dir).is_dir():
        print(f"not a directory: {a.skill_dir}", file=sys.stderr)
        return 2
    results = audit(a.skill_dir)
    order = {"high": 0, "warn": 1, "info": 2}
    results.sort(key=lambda f: (order[f["severity"]], f["file"], f["line"]))
    serious = [f for f in results if f["severity"] in ("high", "warn")]
    if a.json:
        print(json.dumps({"skill": a.skill_dir, "findings": results,
                          "high": sum(f["severity"] == "high" for f in results),
                          "warn": sum(f["severity"] == "warn" for f in results)}, indent=2))
    else:
        for f in results:
            loc = f"{f['file']}:{f['line']}" if f["line"] else f["file"]
            print(f"{f['severity'].upper():5} {f['rule']:24} {loc}: {f['message']}")
            if f["text"]:
                print(f"      > {f['text']}")
        high = sum(f["severity"] == "high" for f in results)
        print(f"\n{high} high, {len(serious) - high} warn, {len(results) - len(serious)} info")
        if high:
            print("Do not install until every HIGH finding is explained.")
    return 1 if serious else 0


if __name__ == "__main__":
    sys.exit(main())
