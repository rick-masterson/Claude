#!/usr/bin/env python3
"""Check skill folders against the open Agent Skills specification (agentskills.io/specification) and the
portability rules that let one SKILL.md work in Claude Code, Codex, Gemini CLI and other agents.

Usage: validate_skill.py SKILL_DIR [SKILL_DIR ...] [--json]
       validate_skill.py --all ROOT        (every folder under ROOT that holds a SKILL.md)
Exit codes: 0 valid (warnings allowed), 1 errors found, 2 bad usage.
"""
import argparse
import json
import re
import sys
from pathlib import Path

SPEC_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
# Fields some agents add; legal to keep, but other agents ignore them.
KNOWN_EXTRA = {"version", "author", "tags", "argument-hint", "disable-model-invocation", "user-invocable", "model",
               "context", "agent", "hooks", "when_to_use", "when-to-use", "paths"}
TOOL_WORDS = re.compile(r"\b(AskUserQuestion|TodoWrite|TaskCreate|WebFetch|WebSearch|NotebookEdit|ExitPlanMode|"
                        r"SendMessage|the (Read|Edit|Write|Glob|Grep|Bash) tool)\b")


def parse(text):
    """Return (frontmatter dict, body, error). Handles the YAML subset skills use: scalars, folded/literal
    blocks, quoted strings and one level of mapping (metadata)."""
    if not text.startswith("---\n"):
        return None, text, "SKILL.md must start with a '---' YAML front matter line"
    end = text.find("\n---", 4)
    if end == -1:
        return None, text, "front matter is not closed with '---'"
    fm, body = text[4:end], text[end + 4:].lstrip("\n")
    fields, key, block = {}, None, None
    for line in fm.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            key, val = m.group(1), m.group(2).strip()
            block = val in ("|", ">", "|-", ">-", "")
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            fields[key] = {} if (key == "metadata" and val == "") else ("" if block else val)
        elif key and line.startswith((" ", "\t")):
            if isinstance(fields[key], dict):
                mm = re.match(r"^\s+([A-Za-z0-9_.-]+):\s*(.*)$", line)
                if mm:
                    fields[key][mm.group(1)] = mm.group(2).strip().strip("\"'")
            else:
                fields[key] = (fields[key] + " " + line.strip()).strip()
        else:
            return fields, body, f"cannot parse front matter line: {line!r}"
    return fields, body, None


def check(skill_dir):
    d = Path(skill_dir)
    errors, warnings = [], []
    f = d / "SKILL.md"
    if not f.is_file():
        return {"skill": str(d), "errors": ["no SKILL.md"], "warnings": []}
    text = f.read_text(errors="replace")
    fields, body, err = parse(text)
    if err:
        errors.append(err)
    fields = fields or {}

    name = fields.get("name", "")
    if not name:
        errors.append("missing required field 'name'")
    else:
        if len(name) > 64:
            errors.append(f"name is {len(name)} chars (max 64)")
        if not re.fullmatch(r"[a-z0-9-]+", name):
            errors.append("name may only contain lowercase letters, digits and hyphens")
        if name.startswith("-") or name.endswith("-") or "--" in name:
            errors.append("name must not start or end with a hyphen or contain '--'")
        if name != d.resolve().name:
            errors.append(f"name '{name}' must match the folder name '{d.resolve().name}'")
        if re.search(r"anthropic|claude", name):
            warnings.append("name contains 'claude' or 'anthropic', which Anthropic's API rejects")

    desc = fields.get("description", "")
    if not desc:
        errors.append("missing required field 'description'")
    else:
        if len(desc) > 1024:
            errors.append(f"description is {len(desc)} chars (max 1024)")
        if re.search(r"<[A-Za-z/][^>]*>", desc):
            warnings.append("description contains XML/HTML tags, which Anthropic's API rejects")
        if re.match(r"^(I|I'm|We|You can|You should|Use me)\b", desc):
            warnings.append("write the description in the third person ('Checks X. Use when Y.')")
        if not re.search(r"\b(use (it |this )?(when|for|before|after|to)|when (the user|you|asked)|trigger)", desc,
                         re.I):
            warnings.append("description should say when to use the skill ('Use when ...')")
        if len(desc) < 60:
            warnings.append("description is very short; agents pick skills from it, so name the tasks and keywords")

    comp = fields.get("compatibility")
    if comp is not None and not 1 <= len(comp) <= 500:
        errors.append("compatibility must be 1-500 characters")
    if "metadata" in fields and not isinstance(fields["metadata"], dict):
        errors.append("metadata must be a mapping of string keys to string values")
    for k in fields:
        if k not in SPEC_FIELDS:
            warnings.append(f"front matter field '{k}' is not in the open spec; other agents ignore it")

    lines = body.count("\n") + 1
    if lines > 500:
        warnings.append(f"SKILL.md body is {lines} lines; keep it under 500 and move detail to references/")
    if TOOL_WORDS.search(body):
        warnings.append(f"body names an agent-specific tool ({TOOL_WORDS.search(body).group(0)}); "
                        "describe the action instead so other agents can follow it")
    if re.search(r"[A-Za-z]:\\\\|\\\\[A-Za-z]", body):
        warnings.append("use forward slashes in paths")

    refs = re.findall(r"\]\(([^)#\s]+)\)|(?<![\w/.$}])((?:scripts|references|assets)/[\w./-]*\w)", body)
    for link, bare in dict.fromkeys(refs):
        t = link or bare
        if re.match(r"^[a-z]+://", t) or t.startswith(("mailto:", "#")) or "$" in t:
            continue
        p = (d / t).resolve()
        if not p.exists():
            (errors if link else warnings).append(
                f"{'linked' if link else 'mentioned'} file does not exist: {t}")
        elif d.resolve() not in p.parents and p != d.resolve():
            errors.append(f"reference points outside the skill folder: {t}")
        elif len(Path(t).parts) > 2:
            warnings.append(f"reference '{t}' is more than one level deep")

    return {"skill": str(d), "name": name, "errors": errors, "warnings": warnings}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dirs", nargs="*")
    ap.add_argument("--all", metavar="ROOT")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    dirs = list(a.dirs)
    if a.all:
        dirs += sorted(str(p.parent) for p in Path(a.all).rglob("SKILL.md") if ".git" not in p.parts)
    if not dirs:
        ap.print_usage(sys.stderr)
        return 2
    results = [check(x) for x in dirs]
    if a.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            state = "FAIL" if r["errors"] else ("warn" if r["warnings"] else "ok")
            print(f"{state:4} {r['skill']}")
            for e in r["errors"]:
                print(f"     error: {e}")
            for w in r["warnings"]:
                print(f"     warn:  {w}")
    return 1 if any(r["errors"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
