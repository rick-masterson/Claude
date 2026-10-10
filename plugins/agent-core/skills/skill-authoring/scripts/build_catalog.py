#!/usr/bin/env python3
"""Turn a folder of skills into something any model can use, including models with no skill support.

  build_catalog.py ROOT                 Markdown index: one line per skill (name, when to use, path).
                                        Paste it into a system prompt; tell the model to read the SKILL.md
                                        for a task that matches.
  build_catalog.py ROOT --bundle        One Markdown file holding every SKILL.md in full, for models that
                                        cannot read files (larger; prefer the index when files are readable).
  build_catalog.py ROOT --json          The index as JSON (name, description, path), for orchestrators.

Exit codes: 0 ok, 1 a skill could not be read, 2 bad usage.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_skill import parse  # noqa: E402

PREAMBLE = """# Available skills

Each skill is a folder with a SKILL.md file of instructions, plus optional scripts/ and references/.
Before starting a task, check this list. If a skill matches, read its SKILL.md and follow it; open its
other files only when the SKILL.md points to them. Paths are relative to {root}.
"""


def collect(root):
    out, bad = [], 0
    for f in sorted(Path(root).rglob("SKILL.md")):
        if ".git" in f.parts:
            continue
        fields, body, err = parse(f.read_text(errors="replace"))
        if err or not fields or not fields.get("name"):
            print(f"skipped {f}: {err or 'no name'}", file=sys.stderr)
            bad += 1
            continue
        out.append({"name": fields["name"], "description": fields.get("description", ""),
                    "path": str(f.relative_to(root)), "body": body})
    return out, bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bundle", action="store_true")
    g.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if not Path(a.root).is_dir():
        print(f"not a directory: {a.root}", file=sys.stderr)
        return 2
    skills, bad = collect(a.root)
    if a.json:
        print(json.dumps([{k: s[k] for k in ("name", "description", "path")} for s in skills], indent=2))
    elif a.bundle:
        print(PREAMBLE.format(root=a.root).replace("Paths are relative", "Script paths are relative"))
        for s in skills:
            print(f"\n---\n\n## Skill: {s['name']}\n\n_When to use:_ {s['description']}\n\n"
                  f"_Folder:_ `{Path(s['path']).parent}`\n\n{s['body'].strip()}\n")
    else:
        print(PREAMBLE.format(root=a.root))
        for s in skills:
            print(f"- **{s['name']}** (`{s['path']}`): {s['description']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
