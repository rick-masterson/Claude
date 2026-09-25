---
name: debian-package
description: Build, review or debug a Debian/Ubuntu .deb package, especially one built by hand with dpkg-deb, and its maintainer scripts (preinst, postinst, prerm, postrm). Use when creating a .deb, editing DEBIAN/control or postinst/postrm, when an install or upgrade does something unexpected, or before publishing a package others will install.
---

# Debian packages without surprises

A package with a wrong maintainer script installs fine and does the damage later: a theme silently becomes the
system default, a user's file is overwritten, or removal leaves the system half-configured. **Check the built .deb
and watch its scripts run in a sandbox before anyone installs it.** Neither step needs root.

## 1. Static check

```bash
python3 scripts/check_deb.py PACKAGE.deb [--json] [--strict]
```

It covers control fields, md5sums (conffiles are excluded, as `dh_md5sums` does), root:root ownership, permissions,
files shipped into `/home`, `/root`, `/tmp` or `/usr/local`, `sh -n` on the scripts, missing `set -e` (either form),
scripts touching home directories, and `update-alternatives --install`. It was validated on 200 random real Debian
packages from an apt cache: 0 errors, and each warning was reviewed. Exit codes: 0 ok, 1 errors, 2 bad usage.

## 2. Watch the maintainer scripts run: sandbox

```bash
python3 scripts/sandbox_maintscripts.py PACKAGE.deb [--lifecycle install,upgrade,remove,purge] \
    [--seed /etc/motd] [--seed /usr/share/foo/motd=/etc/motd] [--old-version 1.0-1] [--json] [--keep]
```

- It runs each script under **bubblewrap**: the real filesystem is read-only, `/home`, `/root` and `/tmp` are empty,
  there is no network, and `DPKG_ROOT` points at a scratch root.
- System tools (`update-alternatives`, `systemctl`, `update-initramfs`, `adduser`, ...) are stubs that only record
  the call.
- It reports every file created, changed or deleted, every tool the scripts *would* run, and all their output.
- `--seed` recreates the target machine's state first. Test the cases that matter: the stock file, a hand-edited
  one, and none at all.
- A script that ignores `DPKG_ROOT` and writes to the real system fails with "Read-only file system". That is a
  finding: the script needs `ROOT=${DPKG_ROOT:-}` in front of every absolute path it touches.

## 3. Rules that prevent the classic mistakes

- **Never touch a user's home from a package.** Ship a per-user command (for example `foo-theme apply|revert`)
  that backs up whatever it replaces, and let the user run it.
- **Installing must not switch anything.** Don't make yourself the default display manager, boot theme, editor or
  shell. `update-alternatives --install` with no other candidate *becomes the default*, whatever its priority. Find
  out how the distro really selects the thing (a config file? a tool?) and leave selection to the user.
- **Taking over a file no package owns** (`dpkg -S` finds nothing; `/etc/motd` is the classic case): only take it
  while it still equals the stock copy (or is empty); back it up once (`foo.pre-<pkg>`); and restore it in
  `postrm remove|purge`, but only if it is still yours. Leave a hand-edited file alone and say so on stderr.
- **Idempotent:** `postinst configure` runs on every upgrade. Running it twice must change nothing.
- **Make every path in a maintainer script `$ROOT/...` with `ROOT=${DPKG_ROOT:-}`**, and skip host-only actions
  (`update-initramfs`, asking the running system) when `ROOT` is set. That is what makes the sandbox, and `dpkg
  --root`, work.
- **Build:** use `dpkg-deb --root-owner-group --build`, set directories to 0755 and files to 0644 (scripts and
  `usr/bin/*` 0755), generate `md5sums`, and set `Installed-Size` (`du -sk` of the payload).
- **Versions:** apt upgrades only when the version increases. Bump `Version:` and add a changelog entry for every
  published change.
- **Test it for real, once:** `sudo apt install ./pkg.deb`, then check the result on the machine
  (`dpkg -L pkg`, `ls -l` on the files the scripts touch). The sandbox narrows the risk; it does not replace this.
