---
name: skill-authoring
description: Writes, validates and packages agent skills in the open SKILL.md format so one skill works in Claude Code, Codex, Gemini CLI and other agents, and turns a skill folder into an index or a single bundle for models without skill support. Use when creating or editing a skill, checking a skill against the spec, or giving a set of skills to another model.
license: GPL-2.0-only
---

# Write skills any agent can use

The format is the open Agent Skills standard (agentskills.io/specification): a folder named after the
skill, holding `SKILL.md` (YAML front matter + Markdown) and optional `scripts/`, `references/`, `assets/`.

## Rules that matter

- `name`: 1-64 chars, lowercase letters, digits, hyphens; no leading, trailing or double hyphen; equals the
  folder name. Avoid "claude" and "anthropic" (Anthropic's API rejects them).
- `description` (max 1024 chars, no XML tags): third person, what it does **and** when to use it, with the
  words a user would actually say. It is the only part every session loads, so it decides when the skill fires.
- Body under 500 lines (about 5,000 tokens). Put detail in `references/`, linked one level deep from SKILL.md.
- Write for a capable reader: only what the agent would not already know. Concrete commands beat prose.
- Portable wording: say "search the files" or "ask the user", not one agent's tool names. Forward slashes.
- Scripts: self-contained (stdlib where possible), `--json` output, exit codes 0 ok / 1 problems / 2 usage,
  clear error messages. A script is better than instructions whenever the check can be mechanical.
- Prefer checklists and a validate-fix-repeat loop for anything fragile.
- Test on something known-good and something known-bad before shipping.

## Validate

```bash
python3 scripts/validate_skill.py path/to/skill            # or: --all path/to/folder
```

Errors are spec violations (exit 1); warnings are portability or quality issues. Then run the security
scan from the `skill-audit` skill: your own skill should have no HIGH findings either.

## Use skills with any model

```bash
python3 scripts/build_catalog.py path/to/skills            # index: one line per skill, for a system prompt
python3 scripts/build_catalog.py path/to/skills --bundle   # every SKILL.md in one file (no file access)
python3 scripts/build_catalog.py path/to/skills --json     # for an orchestrator
```

Agents that support the standard read skills from their own folder; `.agents/skills/` is the shared
location several agents check. For any other model, put the index in the system prompt and let it read the
matching SKILL.md when a task fits; use the bundle only when the model cannot read files.

Sources: agentskills.io specification; Anthropic "Skill authoring best practices".
