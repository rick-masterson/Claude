# Claude — skillset

Skills that make AI coding agents **better at the work, not just faster**. Each skill carries two things:
- **Facts that were verified, not remembered:** checked against source code or a real system, with the source cited.
- **Tools that let an agent check its own output:** static checkers, renderers and anything else with a clear pass/fail.

## Where this is going

This repo is one piece of a collaborative workspace for several AI systems. Claude works in it today; other models
and tools join as they become useful. **ORAC**, a local reasoning node that verifies claims against real sources,
becomes the local orchestrator once it is capable enough. Until then Claude drives, and everything here is built so
that any participant can use it:
- Skills use the open `SKILL.md` format: YAML front matter (`name`, `description`) plus Markdown instructions. That
  is readable by Claude Code and by any agent or person.
- Scripts are plain command-line tools: Python stdlib where possible, `--json` output, and documented exit codes
  (0 ok, 1 found problems, 2 bad usage). An orchestrator can call them as verification steps and read the result
  without parsing prose.
- Nothing here is private. Project-specific or machine-specific skills live in each project's own
  `.claude/skills/`, not in this public repo.

## Plugins

| Plugin | Skills | What it adds |
|---|---|---|
| [`desktop-theming`](plugins/desktop-theming) | `plymouth-theme`, `kde-splash` | Linux boot and login splashes, which fail *silently*: a Plymouth script checker built from Plymouth's source, and an offscreen KSplash renderer that reports QML errors and saves a screenshot |

## Install (Claude Code)

```
/plugin marketplace add rick-masterson/Claude
/plugin install desktop-theming@rick-masterson
```

## Use without Claude Code

```bash
python3 plugins/desktop-theming/skills/plymouth-theme/scripts/check_plymouth_theme.py /usr/share/plymouth/themes/<name> --json
python3 plugins/desktop-theming/skills/kde-splash/scripts/render_splash.py <look-and-feel-dir> --out splash.png --json
```

## Rules for adding a skill

1. **Verify every fact before writing it down**, against source code or the running system, and name the source.
   A confident wrong fact in a skill is worse than none, because every agent that loads it inherits the mistake.
   (The Plymouth checker's first draft flagged valid code three times. It was corrected against Plymouth's source
   and every stock theme installed on the machine before it shipped.)
2. **Ship a tool whenever the check can be mechanical**, and test it on something known-good *and* something
   known-bad.
3. Keep `SKILL.md` short and specific. The `description` decides when the skill loads.
4. `python3 -m unittest discover -s tests` must pass, and `claude plugin validate . --strict` must be clean.

## Licence

GPL-2.0 (see `LICENSE`).
