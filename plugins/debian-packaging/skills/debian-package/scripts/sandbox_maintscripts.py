#!/usr/bin/env python3
"""Run a .deb's maintainer scripts in a throwaway sandbox and report what they would do. No root needed.

    sandbox_maintscripts.py PACKAGE.deb [--lifecycle install,upgrade,remove,purge] [--old-version V]
                            [--seed /etc/motd ...] [--json]

What happens:
  * a scratch root is made; --seed copies real host files into it first (e.g. /etc/motd), so scripts that react
    to existing state can be exercised
  * the package payload is unpacked into the scratch root, as dpkg would
  * each script runs under bubblewrap: the real filesystem is READ-ONLY, /home /root /tmp are empty tmpfs, there
    is no network, and DPKG_ROOT points at the scratch root. System tools a script would call
    (update-alternatives, systemctl, update-initramfs, ...) are replaced by stubs that only log the call
  * between prerm and postrm the payload is removed from the scratch root, as dpkg would

Report: exit code and output of every script, every stubbed call, and every file created, changed or deleted in
the scratch root. A script that writes to the real system fails inside the sandbox ("Read-only file system"), which
shows up in its output. That means it ignores DPKG_ROOT, which is itself worth knowing.

Exit 0: every script exited 0. 1: a script failed. 2: bad usage. 3: bubblewrap (bwrap) is not installed.
Scripts only see the scratch root through DPKG_ROOT; Debian maintainer scripts that honour it (dpkg >= 1.18.5
convention) act on the scratch root, and those that don't hit the read-only real system and fail, safely.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

STUBS = ["update-alternatives", "update-initramfs", "systemctl", "deb-systemd-helper", "deb-systemd-invoke",
         "invoke-rc.d", "update-rc.d", "service", "ldconfig", "dpkg-trigger", "dpkg-divert", "dpkg-statoverride",
         "ucf", "ucfr", "adduser", "addgroup", "useradd", "groupadd", "deluser", "userdel", "update-desktop-database",
         "gtk-update-icon-cache", "update-mime-database", "glib-compile-schemas", "fc-cache", "update-grub",
         "plymouth-set-default-theme", "update-initramfs", "systemd-tmpfiles", "systemd-sysusers", "udevadm",
         "mandb", "install-info", "py3compile", "py3clean", "chown", "chgrp"]

LIFECYCLES = {
    "install": [("preinst", ["install"]), ("unpack", []), ("postinst", ["configure", ""])],
    "upgrade": [("preinst", ["upgrade", "{old}"]), ("unpack", []), ("postinst", ["configure", "{old}"])],
    "remove": [("prerm", ["remove"]), ("remove-files", []), ("postrm", ["remove"])],
    "purge": [("postrm", ["purge"])],
}


def snapshot(root: Path) -> dict:
    snap = {}
    for p in root.rglob("*"):
        rel = "/" + str(p.relative_to(root))
        if p.is_symlink():
            snap[rel] = "link:" + os.readlink(p)
        elif p.is_file():
            snap[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        elif p.is_dir():
            snap[rel] = "dir"
    return snap


def diff(before: dict, after: dict) -> dict:
    return {
        "created": sorted(k for k in after.keys() - before.keys()),
        "deleted": sorted(k for k in before.keys() - after.keys()),
        "changed": sorted(k for k in before.keys() & after.keys() if before[k] != after[k]),
        "symlinks": {k: after[k][5:] for k in sorted(after) if after[k].startswith("link:")
                     and before.get(k) != after[k]},
    }


def make_stubs(stub_dir: Path, log: Path) -> None:
    stub_dir.mkdir(parents=True)
    for name in STUBS:
        s = stub_dir / name
        s.write_text("#!/bin/sh\n"
                     f'printf "%s" "{name}" >> "{log}"\n'
                     f'for a in "$@"; do printf " %s" "$a" >> "{log}"; done\n'
                     f'printf "\\n" >> "{log}"\n'
                     # plymouth-set-default-theme with no args prints the current theme; update-alternatives
                     # --query must not claim an alternative exists
                     'exit 0\n')
        s.chmod(0o755)


def run_script(script: Path, args: list[str], scratch: Path, stubs: Path, log: Path, work: Path) -> dict:
    env_path = f"{stubs}:/usr/sbin:/usr/bin:/sbin:/bin"
    cmd = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
           "--tmpfs", "/home", "--tmpfs", "/root", "--tmpfs", "/tmp",
           "--bind", str(work), str(work),  # scratch root, stubs and log live here, re-exposed read-write
           "--unshare-net", "--unshare-pid", "--die-with-parent",
           "--clearenv", "--setenv", "PATH", env_path, "--setenv", "DPKG_ROOT", str(scratch),
           "--setenv", "HOME", "/home/sandbox", "--setenv", "DPKG_MAINTSCRIPT_NAME", script.name,
           "--setenv", "DPKG_MAINTSCRIPT_PACKAGE", "sandbox", "--setenv", "LC_ALL", "C.UTF-8",
           "--chdir", "/", str(script), *args]
    before = log.read_text() if log.exists() else ""
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    calls = (log.read_text() if log.exists() else "")[len(before):].splitlines()
    return {"exit": r.returncode, "stdout": r.stdout.strip(), "stderr": r.stderr.strip(), "stub_calls": calls}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run a .deb's maintainer scripts in a bubblewrap sandbox.")
    ap.add_argument("deb", type=Path)
    ap.add_argument("--lifecycle", default="install,remove,purge",
                    help=f"comma list of {', '.join(LIFECYCLES)} (default install,remove,purge)")
    ap.add_argument("--old-version", default="0.0-1", help="previous version for the upgrade lifecycle")
    ap.add_argument("--seed", action="append", default=[], metavar="HOST_PATH[=ROOT_PATH]",
                    help="copy a real host file into the scratch root first (repeatable), e.g. /etc/motd, or "
                         "/usr/share/foo/motd=/etc/motd to place it at a different path")
    ap.add_argument("--keep", action="store_true", help="keep the scratch root and print its path")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not args.deb.is_file():
        print(f"{args.deb}: no such file", file=sys.stderr); return 2
    if not shutil.which("bwrap"):
        print("bubblewrap (bwrap) is required: sudo apt install bubblewrap", file=sys.stderr); return 3
    stages = [s.strip() for s in args.lifecycle.split(",") if s.strip()]
    if unknown := [s for s in stages if s not in LIFECYCLES]:
        print(f"unknown lifecycle stage(s): {unknown}", file=sys.stderr); return 2

    work = Path(tempfile.mkdtemp(prefix="maintsandbox-"))
    try:
        scratch, ctrl, payload = work / "root", work / "control", work / "payload"
        scratch.mkdir()
        subprocess.run(["dpkg-deb", "--control", str(args.deb), str(ctrl)], check=True)
        subprocess.run(["dpkg-deb", "--extract", str(args.deb), str(payload)], check=True)
        for seed in args.seed:
            src_s, _, dst_s = seed.partition("=")
            src = Path(src_s)
            dst = scratch / Path(dst_s or src_s).relative_to("/")
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_symlink():
                dst.symlink_to(os.readlink(src))
            elif src.exists():
                shutil.copy2(src, dst)
        log = work / "stub-calls.log"
        make_stubs(work / "stubs", log)
        shipped = sorted("/" + str(p.relative_to(payload)) for p in payload.rglob("*")
                         if p.is_file() or p.is_symlink())

        steps, failed = [], False
        for stage in stages:
            for name, raw_args in LIFECYCLES[stage]:
                before = snapshot(scratch)
                if name == "unpack":
                    shutil.copytree(payload, scratch, symlinks=True, dirs_exist_ok=True)
                    steps.append({"stage": stage, "step": "unpack payload (dpkg)", "files": diff(before, snapshot(scratch))})
                    continue
                if name == "remove-files":
                    for rel in shipped:
                        p = scratch / rel.lstrip("/")
                        if p.is_symlink() or p.is_file():
                            p.unlink()
                    steps.append({"stage": stage, "step": "remove payload (dpkg)", "files": diff(before, snapshot(scratch))})
                    continue
                script = ctrl / name
                if not script.exists():
                    continue
                call_args = [a.format(old=args.old_version) for a in raw_args]
                res = run_script(script, call_args, scratch, work / "stubs", log, work)
                res.update({"stage": stage, "step": f"{name} {' '.join(call_args)}".strip(),
                            "files": diff(before, snapshot(scratch))})
                failed |= res["exit"] != 0
                steps.append(res)

        report = {"deb": str(args.deb), "ok": not failed, "steps": steps}
        if args.keep:
            report["scratch_root"] = str(scratch)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            for s in steps:
                head = s["step"] + (f"  -> exit {s['exit']}" if "exit" in s else "")
                print(f"== [{s['stage']}] {head}")
                f = s["files"]
                if "exit" not in s:
                    print(f"   {len(f['created'])} created, {len(f['deleted'])} deleted")
                    continue
                for c in s.get("stub_calls", []):
                    print(f"   would run: {c}")
                for kind in ("created", "changed", "deleted"):
                    for p in f[kind]:
                        extra = f" -> {f['symlinks'][p]}" if p in f["symlinks"] else ""
                        print(f"   {kind}: {p}{extra}")
                for stream in ("stdout", "stderr"):
                    for line in s[stream].splitlines():
                        print(f"   {stream}: {line}")
            print(("OK" if not failed else "FAIL") + f": {args.deb.name}"
                  + (f"  (scratch root kept: {scratch})" if args.keep else ""))
        return 1 if failed else 0
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
