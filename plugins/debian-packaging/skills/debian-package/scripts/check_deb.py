#!/usr/bin/env python3
"""Static checks for a built .deb: the mistakes that install fine and bite later.

    check_deb.py PACKAGE.deb [--json] [--strict]

Exit 0: no errors (warnings allowed unless --strict). 1: errors. 2: bad usage or unreadable package.
Needs dpkg-deb (present on any Debian-family system). Nothing is installed or executed.

  E  control: a required field missing (Package, Version, Architecture, Maintainer, Description)
  E  a maintainer script that is not executable, or fails `sh -n`
  E  md5sums missing or not matching the payload
  E  files owned by someone other than root:root (build with dpkg-deb --root-owner-group)
  E  files shipped in a user's space (/home, /root) or in /usr/local or /tmp
  E  a world-writable file or directory
  W  no Installed-Size
  W  a maintainer script without `set -e`
  W  a maintainer script writing into a home directory ($HOME, ~/, /home/): a package must never touch user files
  W  `update-alternatives --install`: if it is the only candidate it becomes the default, silently
  W  files under /usr/bin, /usr/sbin or /usr/libexec that are not executable
  W  a conffile listed in DEBIAN/conffiles that the package does not ship
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REQUIRED = ("Package", "Version", "Architecture", "Maintainer", "Description")
MAINT = ("preinst", "postinst", "prerm", "postrm", "config")


def sh(*cmd) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def parse_control(text: str) -> dict:
    fields, key = {}, None
    for line in text.splitlines():
        if line[:1] in (" ", "\t") and key:
            fields[key] += "\n" + line.strip()
        elif ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            fields[key] = val.strip()
    return fields


def check(deb: Path) -> list[dict]:
    issues = []
    add = lambda level, msg: issues.append({"level": level, "message": msg})

    listing = sh("dpkg-deb", "--contents", str(deb))
    if listing.returncode:
        raise SystemExit(f"{deb}: not a readable .deb: {listing.stderr.strip()}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        ctrl, data = tmp / "DEBIAN", tmp / "root"
        sh("dpkg-deb", "--control", str(deb), str(ctrl))
        sh("dpkg-deb", "--extract", str(deb), str(data))

        fields = parse_control((ctrl / "control").read_text(encoding="utf-8", errors="replace"))
        for f in REQUIRED:
            if not fields.get(f):
                add("error", f"control: missing {f}")
        if "Installed-Size" not in fields:
            add("warning", "control: no Installed-Size (apt shows 0 kB and can't plan disk space)")

        for name in MAINT:
            p = ctrl / name
            if not p.exists():
                continue
            if not p.stat().st_mode & 0o111:
                add("error", f"{name}: not executable (dpkg will refuse it)")
            text = p.read_text(encoding="utf-8", errors="replace")
            if text.startswith("#!") and "sh" in text.splitlines()[0]:
                syntax = sh("sh", "-n", str(p))
                if syntax.returncode:
                    add("error", f"{name}: shell syntax error: {syntax.stderr.strip()}")
                shebang_e = re.match(r"#!\S*sh\s+-[a-z]*e", text.splitlines()[0])  # e.g. `#!/bin/sh -e`
                if not shebang_e and not re.search(r"(?m)^\s*set\s+-[a-z]*e", text):
                    add("warning", f"{name}: no `set -e`; a failing command will be ignored")
            code = "\n".join(l.split("#", 1)[0] for l in text.splitlines())
            if re.search(r"\$HOME\b|\$\{HOME\}|(?<![\w/])~/|/home/", code):
                add("warning", f"{name}: writes to or reads from a home directory; a package must not touch "
                    "user files (ship a per-user command the user runs instead)")
            if re.search(r"update-alternatives\s+--install", code):
                add("warning", f"{name}: `update-alternatives --install`: when this is the only candidate for the "
                    "link it becomes the default on install, whatever the priority")

        conffiles = ctrl / "conffiles"
        conf = {c.lstrip("/") for c in conffiles.read_text().split()} if conffiles.exists() else set()
        md5 = ctrl / "md5sums"
        if not md5.exists():
            add("error", "no DEBIAN/md5sums (debsums and dpkg --verify cannot check the install)")
        else:
            listed = {}
            for line in md5.read_text().splitlines():
                if line.strip():
                    digest, _, path = line.partition("  ")
                    listed[path] = digest
            shipped = {str(p.relative_to(data)) for p in data.rglob("*") if p.is_file() and not p.is_symlink()}
            for path in sorted(shipped - listed.keys() - conf):  # conffiles are left out by convention (dh_md5sums)
                add("error", f"md5sums: {path} is shipped but not listed")
            for path in sorted(listed.keys() - shipped):
                add("error", f"md5sums: {path} is listed but not shipped")
            for path in sorted(listed.keys() & shipped):
                if hashlib.md5((data / path).read_bytes()).hexdigest() != listed[path]:
                    add("error", f"md5sums: {path} does not match")

        for c in sorted(conf):
            if not (data / c).exists():
                add("warning", f"conffiles: /{c} is listed but not shipped")

    for line in listing.stdout.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        mode, owner, path = parts[0], parts[1], parts[5].split(" -> ")[0]
        path = path[1:] if path.startswith(".") else path
        if owner != "root/root":
            add("error", f"{path}: owned by {owner}, not root/root (build with dpkg-deb --root-owner-group)")
        sticky_dir = mode[0] == "d" and mode[-1] in "tT"  # /tmp-style shared directories are meant to be 1777
        if len(mode) >= 9 and mode[8] == "w" and mode[0] != "l" and not sticky_dir:
            add("error", f"{path}: world-writable ({mode})")
        # The directories themselves are legitimately created by base-files; shipping CONTENT there is the error.
        if mode[0] != "d" and re.match(r"^/(home|root|tmp|usr/local)/", path):
            add("error", f"{path}: packages must not ship files in /{path.split('/')[1]}/")
        if mode[0] == "-" and re.match(r"^/usr/(s?bin|libexec)/", path) and "x" not in mode:
            add("warning", f"{path}: in a program directory but not executable ({mode})")
    return issues


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Static checks for a built .deb.")
    ap.add_argument("deb", type=Path)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = ap.parse_args(argv)
    if not args.deb.is_file():
        print(f"{args.deb}: no such file", file=sys.stderr)
        return 2
    try:
        issues = check(args.deb)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    bad = [i for i in issues if i["level"] == "error" or (args.strict and i["level"] == "warning")]
    if args.json:
        print(json.dumps({"deb": str(args.deb), "ok": not bad, "issues": issues}, indent=2))
    else:
        for i in issues:
            print(f"{i['level'].upper():7} {i['message']}")
        print(f"{'OK' if not bad else 'FAIL'}: {sum(i['level'] == 'error' for i in issues)} error(s), "
              f"{sum(i['level'] == 'warning' for i in issues)} warning(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
