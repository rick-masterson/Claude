#!/usr/bin/env python3
"""Static checker for Plymouth `script`-module themes.

    check_plymouth_theme.py THEME_DIR_OR_.script [--json] [--strict]

Exit 0: no errors (warnings allowed unless --strict). Exit 1: errors found. Exit 2: bad usage.

Catches the mistakes that look plausible and fail silently at boot. Plymouth prints nothing on screen for a
script error; the splash just doesn't animate, or falls back to text.
  E  Plymouth.<fn> that the script plugin does not provide (e.g. GetTime)
  E  a Sprite method that does not exist (e.g. SetScale: a Sprite cannot scale, its Image can: img.Scale(w, h))
  E  Image("file") whose file is not in the theme directory
  E  .plymouth descriptor problems: ModuleName not `script`, or ScriptFile not present
  W  a sprite assigned, inside a function, to a name that is not a global: Plymouth makes it a local, which is
     freed, and the sprite vanishes, on return. (Assigning to an EXISTING global inside a function does update
     it: names resolve local -> this -> global, per script-execute.c.)
  I  Image.Text needs a text renderer plugin (Debian/Ubuntu: plymouth-label), and must be in the initramfs

The API lists are read from Plymouth's source (main @ 29acf726): the natives in src/plugins/splash/script/
script-lib-*.c and the names its bundled script-lib-*.script files add. They were validated by running this checker
over every script theme installed on a Debian/Shadowfetch machine, all of which boot. Stdlib only, so any agent or CI
can run it.
"""
from __future__ import annotations

import argparse
import configparser
import json
import re
import sys
from pathlib import Path

# From Plymouth main @ 29acf726 (2026-09-21): natives registered in script-lib-plymouth.c / script-lib-sprite.c,
# plus names the bundled script libraries define (script-lib-plymouth.script, script-lib-sprite.script).
PLYMOUTH_FUNCS = {
    "SetRefreshFunction", "SetBootProgressFunction", "SetRootMountedFunction", "SetKeyboardInputFunction",
    "SetUpdateStatusFunction", "SetDisplayNormalFunction", "SetDisplayPasswordFunction",
    "SetDisplayQuestionFunction", "SetDisplayPromptFunction", "SetDisplayMessageFunction",
    "SetHideMessageFunction", "SetQuitFunction", "SetSystemUpdateFunction", "SetValidateInputFunction",
    "SetDisplayHotplugFunction", "SetRefreshRate", "GetMode", "GetCapslockState",
    "SetMessageFunction",  # compatibility alias for SetDisplayMessageFunction (script-lib-plymouth.script)
}
SPRITE_METHODS = {"SetImage", "GetImage", "SetX", "SetY", "SetZ", "GetX", "GetY", "GetZ",
                  "SetOpacity", "GetOpacity", "SetPosition"}  # SetPosition: script-lib-sprite.script
KNOWN_MISTAKES = {
    "GetTime": "there is no clock; count ticks in the refresh callback (50 per second by default)",
}


def strip_comments(src: str) -> str:
    """Blank out #, // and /* */ comments, leaving strings and line numbers intact."""
    out, i, n, in_str = [], 0, len(src), False
    while i < n:
        c = src[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True; out.append(c); i += 1
        elif c == "#" or src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2); j = n if j < 0 else j + 2
            out.append("".join(ch if ch == "\n" else " " for ch in src[i:j])); i = j
        else:
            out.append(c); i += 1
    return "".join(out)


def line_of(src: str, pos: int) -> int:
    return src.count("\n", 0, pos) + 1


def function_bodies(code: str) -> list[tuple[str, int, int]]:
    """(name, body_start, body_end) for each `fun name(...) { ... }`."""
    bodies = []
    for m in re.finditer(r"\bfun\s+(\w+)\s*\([^)]*\)\s*\{", code):
        depth, j = 1, m.end()
        while j < len(code) and depth:
            depth += {"{": 1, "}": -1}.get(code[j], 0)
            j += 1
        bodies.append((m.group(1), m.end(), j - 1))
    return bodies


def check_script(path: Path, image_dir: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    code = strip_comments(raw)
    issues = []

    def add(level, pos, msg):
        issues.append({"level": level, "file": path.name, "line": line_of(code, pos), "message": msg})

    for m in re.finditer(r"\bPlymouth\.(\w+)", code):
        name = m.group(1)
        if name not in PLYMOUTH_FUNCS:
            hint = KNOWN_MISTAKES.get(name, "not provided by the script plugin")
            add("error", m.start(), f"Plymouth.{name} does not exist: {hint}")

    # Names holding sprites: `x = Sprite(`, `a.b = Sprite(`, `d[i].s = Sprite(`. Index expressions are normalised.
    norm = lambda s: re.sub(r"\[[^\]]*\]", "[]", s.replace(" ", ""))
    sprite_vars = {norm(m.group(1)) for m in re.finditer(r"([\w.\[\]]+)\s*=\s*Sprite\s*\(", code)}
    for m in re.finditer(r"([\w.\[\]]+)\.(\w+)\s*\(", code):
        target, method = norm(m.group(1)), m.group(2)
        if method == "SetScale":
            add("error", m.start(), f"{m.group(1)}.SetScale(): Sprites cannot scale. Scale the Image instead "
                "(img = img.Scale(w, h)) and SetImage() it")
        elif target in sprite_vars and method not in SPRITE_METHODS:
            add("error", m.start(), f"{m.group(1)}.{method}(): not a Sprite method "
                f"(Sprite has {', '.join(sorted(SPRITE_METHODS))})")

    for m in re.finditer(r'\bImage\s*\(\s*"([^"]+)"\s*\)', code):
        if m.group(1).startswith("special://"):  # built-in images such as special://logo, not theme files
            continue
        if not (image_dir / m.group(1)).is_file():
            add("error", m.start(), f'Image("{m.group(1)}"): no such file in {image_dir}')

    top_level = code
    bodies = function_bodies(code)
    for _, a, b in sorted(bodies, key=lambda t: -t[1]):
        top_level = top_level[:a] + " " * (b - a) + top_level[b:]
    globals_ = set(re.findall(r"(?m)^\s*([A-Za-z_]\w*)\s*=(?!=)", top_level))

    # Scoping, from script-execute.c script_evaluate_var(): a bare name resolves local -> this -> global, and only
    # when it exists in none of them is a new LOCAL created. So `x = Sprite()` in a function updates a global x if
    # one exists (Plymouth's own example theme relies on this), but a name with no global becomes a local, freed on
    # return, and a freed sprite leaves the screen.
    for fname, a, b in bodies:
        body = code[a:b]
        params = set(re.findall(r"\w+", re.search(r"\(([^)]*)\)", code[code.rfind("fun", 0, a):a]).group(1)))
        for m in re.finditer(r"(?m)^\s*([A-Za-z_]\w*)\s*=(?!=)\s*Sprite\s*\(", body):
            name = m.group(1)
            if name not in params and name not in globals_:
                add("warning", a + m.start(1), f"in {fname}(): `{name} = Sprite(...)`: `{name}` is not a global, so "
                    "it becomes a local and the sprite disappears when the function returns; create it at top "
                    "level, or keep it in a global object (e.g. ui.sprite)")

    if re.search(r"\bImage\.Text\s*\(", code):
        issues.append({"level": "info", "file": path.name, "line": 0, "message":
                       "uses Image.Text: needs a text renderer (Debian/Ubuntu: plymouth-label) in the initramfs; "
                       "check with: sudo lsinitramfs /boot/initrd.img-$(uname -r) | grep label"})
    return issues


def check_descriptor(desc: Path) -> list[dict]:
    issues = []
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(desc, encoding="utf-8")
    add = lambda level, msg: issues.append({"level": level, "file": desc.name, "line": 0, "message": msg})
    module = cp.get("Plymouth Theme", "ModuleName", fallback=None)
    if module != "script":
        add("error", f"ModuleName is {module!r}; this checker covers script themes (ModuleName=script)")
    script = cp.get("script", "ScriptFile", fallback=None)
    image_dir = cp.get("script", "ImageDir", fallback=None)
    if not script:
        add("error", "no [script] ScriptFile")
    elif not (desc.parent / Path(script).name).is_file():
        add("error", f"ScriptFile {script} has no {Path(script).name} beside the descriptor")
    if image_dir and Path(image_dir).name != desc.parent.name:
        add("warning", f"ImageDir {image_dir} does not end in the theme's own directory name {desc.parent.name}/; "
            "Plymouth loads from the installed path, not from here")
    return issues


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check a Plymouth script theme for silent boot-time failures.")
    ap.add_argument("target", type=Path, help="theme directory (with a .plymouth file) or a .script file")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = ap.parse_args(argv)

    t = args.target
    if t.is_dir():
        descs = sorted(t.glob("*.plymouth"))
        scripts = sorted(t.glob("*.script"))
        image_dir = t
    elif t.suffix == ".script" and t.is_file():
        descs, scripts, image_dir = [], [t], t.parent
    else:
        print(f"{t}: not a theme directory or .script file", file=sys.stderr)
        return 2
    if not scripts:
        print(f"{t}: no .script file", file=sys.stderr)
        return 2

    issues = [i for d in descs for i in check_descriptor(d)]
    issues += [i for s in scripts for i in check_script(s, image_dir)]
    errors = [i for i in issues if i["level"] == "error" or (args.strict and i["level"] == "warning")]

    if args.json:
        print(json.dumps({"target": str(t), "ok": not errors, "issues": issues}, indent=2))
    else:
        for i in issues:
            loc = f"{i['file']}:{i['line']}" if i["line"] else i["file"]
            print(f"{i['level'].upper():7} {loc}  {i['message']}")
        print(f"{'OK' if not errors else 'FAIL'}: {sum(i['level'] == 'error' for i in issues)} error(s), "
              f"{sum(i['level'] == 'warning' for i in issues)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
