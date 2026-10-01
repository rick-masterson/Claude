"""Tests for the debian-packaging plugin: check_deb.py, sandbox_maintscripts.py, verify_apt_repo.py and the
build-repo.sh template. Packages, a signed repository and a throwaway signing key are built on the fly.

check_deb's rules were also validated on 200 random real Debian packages (0 errors); the false positives found
there are pinned here: conffiles are left out of md5sums, sticky /tmp-style directories are 1777, and
`#!/bin/sh -e` counts as set -e.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SK = ROOT / "plugins" / "debian-packaging" / "skills"
CHECK = SK / "debian-package" / "scripts" / "check_deb.py"
SANDBOX = SK / "debian-package" / "scripts" / "sandbox_maintscripts.py"
VERIFY = SK / "apt-repo-github" / "scripts" / "verify_apt_repo.py"
TEMPLATE = SK / "apt-repo-github" / "templates" / "build-repo.sh"


def run(*cmd, env=None):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env)


def build_deb(out: Path, *, name="demo", control_extra="", postinst=None, files=None, conffiles=(),
              bad_md5=False, dirs=()) -> Path:
    stage = Path(tempfile.mkdtemp())
    try:
        (stage / "DEBIAN").mkdir()
        for rel, text in (files or {"usr/share/demo/hello.txt": "hello\n"}).items():
            p = stage / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        for d in dirs:
            (stage / d).mkdir(parents=True, exist_ok=True)
        control = (f"Package: {name}\nVersion: 1.0-1\nArchitecture: all\nMaintainer: T <t@example.org>\n"
                   f"Installed-Size: 1\nDescription: demo\n demo package\n{control_extra}")
        (stage / "DEBIAN" / "control").write_text(control)
        if postinst is not None:
            (stage / "DEBIAN" / "postinst").write_text(postinst)
            (stage / "DEBIAN" / "postinst").chmod(0o755)
        if conffiles:
            (stage / "DEBIAN" / "conffiles").write_text("".join(f"/{c}\n" for c in conffiles))
        import hashlib
        lines = []
        for p in sorted(stage.rglob("*")):
            rel = str(p.relative_to(stage))
            if p.is_file() and not rel.startswith("DEBIAN") and rel not in conffiles:
                digest = hashlib.md5(p.read_bytes()).hexdigest()
                lines.append(f"{'0' * 32 if bad_md5 else digest}  {rel}\n")
        (stage / "DEBIAN" / "md5sums").write_text("".join(lines))
        for p in stage.rglob("*"):
            if p.is_dir() and not str(p).endswith("tmp"):
                p.chmod(0o755)
        deb = out / f"{name}_1.0-1_all.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage), str(deb)], check=True,
                       capture_output=True)
        return deb
    finally:
        shutil.rmtree(stage, ignore_errors=True)


GOOD_POSTINST = """#!/bin/sh
set -e
ROOT=${DPKG_ROOT:-}
if [ "$1" = configure ]; then
    mkdir -p "$ROOT/etc/demo"
    [ -e "$ROOT/etc/demo/state" ] || echo configured > "$ROOT/etc/demo/state"
    update-desktop-database -q || true
fi
"""


class CheckDeb(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def report(self, deb, *flags):
        r = run(sys.executable, CHECK, deb, "--json", *flags)
        return r.returncode, json.loads(r.stdout)

    def test_well_formed_package_passes(self):
        code, rep = self.report(build_deb(self.tmp, postinst=GOOD_POSTINST))
        self.assertEqual(code, 0, rep)
        self.assertEqual(rep["issues"], [])

    def test_conffile_excluded_from_md5sums_is_fine(self):
        deb = build_deb(self.tmp, files={"etc/demo.conf": "x=1\n"}, conffiles=("etc/demo.conf",))
        self.assertEqual(self.report(deb)[0], 0)

    def test_shebang_dash_e_counts_as_set_e(self):
        deb = build_deb(self.tmp, postinst="#!/bin/sh -e\ntrue\n")
        self.assertFalse(any("set -e" in i["message"] for i in self.report(deb)[1]["issues"]))

    def test_each_defect_is_reported(self):
        bad_postinst = ("#!/bin/sh\ncp /usr/share/demo/x \"$HOME/.config/x\"\n"
                        "update-alternatives --install /usr/bin/ed ed /usr/bin/demo 50\n")
        deb = build_deb(self.tmp, postinst=bad_postinst, bad_md5=True,
                        files={"usr/local/bin/demo": "x\n", "usr/share/demo/a": "a\n"})
        code, rep = self.report(deb)
        text = " | ".join(i["message"] for i in rep["issues"])
        self.assertEqual(code, 1)
        for needle in ("does not match", "must not ship files in /usr/", "no `set -e`", "home directory",
                       "update-alternatives --install"):
            self.assertIn(needle, text)

    def test_missing_control_field_is_an_error(self):
        deb = build_deb(self.tmp)
        stage = self.tmp / "x"
        subprocess.run(["dpkg-deb", "-R", str(deb), str(stage)], check=True)
        ctl = stage / "DEBIAN" / "control"
        ctl.write_text("\n".join(l for l in ctl.read_text().splitlines() if not l.startswith("Maintainer")) + "\n")
        broken = self.tmp / "broken.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "-b", str(stage), str(broken)], check=True,
                       capture_output=True)
        code, rep = self.report(broken)
        self.assertEqual(code, 1)
        self.assertTrue(any("missing Maintainer" in i["message"] for i in rep["issues"]))


def bwrap_works():
    return bool(shutil.which("bwrap")) and run("bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "true").returncode == 0


BWRAP_OK = bwrap_works()
# CI sets REQUIRE_SANDBOX=1 so a runner that cannot create namespaces fails these tests instead of skipping them.
SANDBOX_REQUIRED = os.environ.get("REQUIRE_SANDBOX") == "1"


@unittest.skipUnless(BWRAP_OK or SANDBOX_REQUIRED, "bubblewrap is missing or cannot create namespaces here")
class Sandbox(unittest.TestCase):
    def setUp(self):
        self.assertTrue(BWRAP_OK, "REQUIRE_SANDBOX=1 but bubblewrap cannot create namespaces here")
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def steps(self, deb, *args):
        r = run(sys.executable, SANDBOX, deb, "--json", *args)
        return r.returncode, json.loads(r.stdout)["steps"]

    def test_install_acts_on_the_scratch_root_and_stubs_system_tools(self):
        code, steps = self.steps(build_deb(self.tmp, postinst=GOOD_POSTINST), "--lifecycle", "install")
        post = next(s for s in steps if s["step"].startswith("postinst"))
        self.assertEqual(code, 0)
        self.assertIn("/etc/demo/state", post["files"]["created"])
        self.assertIn("update-desktop-database -q", post["stub_calls"])

    def test_script_ignoring_dpkg_root_cannot_touch_the_real_system(self):
        rogue = "#!/bin/sh\nset -e\necho hacked > /etc/sandbox-escape-test\n"
        code, steps = self.steps(build_deb(self.tmp, postinst=rogue), "--lifecycle", "install")
        post = next(s for s in steps if s["step"].startswith("postinst"))
        self.assertEqual(code, 1)
        self.assertIn("Read-only file system", post["stderr"])
        self.assertFalse(Path("/etc/sandbox-escape-test").exists())

    def test_home_is_empty_inside_the_sandbox(self):
        peek = "#!/bin/sh\nset -e\nls -A /home\n"
        _, steps = self.steps(build_deb(self.tmp, postinst=peek), "--lifecycle", "install")
        self.assertEqual(next(s for s in steps if s["step"].startswith("postinst"))["stdout"], "")

    def postinst(self, script):
        _, steps = self.steps(build_deb(self.tmp, postinst="#!/bin/sh\n" + script), "--lifecycle", "install")
        return next(s for s in steps if s["step"].startswith("postinst"))

    def test_run_is_empty_so_host_sockets_are_unreachable(self):
        self.assertEqual(self.postinst("ls -A /run\n")["stdout"], "")

    def test_a_host_socket_under_run_cannot_be_reached(self):
        import socket
        where = next((d for d in (os.environ.get("XDG_RUNTIME_DIR"), "/run") if d and d.startswith("/run")
                      and os.access(d, os.W_OK)), None)
        if where is None:
            self.skipTest("no writable directory under /run to plant a socket in")
        path = Path(where) / f"sandbox-test-{os.getpid()}.sock"
        srv = socket.socket(socket.AF_UNIX)
        try:
            srv.bind(str(path)); srv.listen(1)
            probe = (f"python3 -c \"import socket; socket.socket(socket.AF_UNIX).connect('{path}')\" "
                     "&& echo REACHED || echo blocked\n")
            self.assertEqual(self.postinst(probe)["stdout"], "blocked")
        finally:
            srv.close(); path.unlink(missing_ok=True)

    def test_capabilities_are_dropped_so_root_cannot_remount_the_real_system(self):
        post = self.postinst("grep CapEff /proc/self/status\n"
                             "mount -o remount,bind,rw / 2>/dev/null && echo REMOUNTED || echo ro\n")
        self.assertEqual(post["stdout"].split(), ["CapEff:", "0000000000000000", "ro"])

    @unittest.skipUnless(Path("/etc/shadow").is_file(), "no /etc/shadow here")
    def test_shadow_reads_as_empty(self):
        self.assertEqual(self.postinst("wc -c < /etc/shadow\n")["stdout"], "0")


def have(*tools):
    return all(shutil.which(t) for t in tools)


@unittest.skipUnless(have("gpg", "gpgv", "apt-ftparchive", "dpkg-deb"), "needs gpg, gpgv, apt-ftparchive")
class AptRepo(unittest.TestCase):
    """Build a signed repository with the template, then verify it, tamper with it, and verify again."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.gnupg = cls.tmp / "gnupg"
        cls.gnupg.mkdir(mode=0o700)
        env = {**os.environ, "GNUPGHOME": str(cls.gnupg)}
        subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-generate-key", "Test APT <t@example.org>",
                        "ed25519", "sign", "1d"], check=True, capture_output=True, env=env)
        key = subprocess.run(["gpg", "--batch", "--armor", "--export-secret-keys"], check=True,
                             capture_output=True, text=True, env=env).stdout
        repo = cls.tmp / "repo"
        (repo / "scripts").mkdir(parents=True)
        (repo / "packages" / "demo").mkdir(parents=True)
        script = TEMPLATE.read_text().replace("@NAME@", "test").replace("@ORIGIN@", "Test") \
            .replace("@DESCRIPTION@", "Test repo")
        (repo / "scripts" / "build-repo.sh").write_text(script)
        debs = cls.tmp / "debs"
        debs.mkdir()
        cls.deb = build_deb(debs, postinst=GOOD_POSTINST)
        # The build script records whether it could see the signing key; it must not.
        (repo / "packages" / "demo" / "build.sh").write_text(
            f'#!/bin/sh\ncp "{cls.deb}" "$1/"\nprintf %s "${{APT_SIGNING_KEY:+LEAKED}}" > "{cls.tmp}/key-seen"\n')
        r = subprocess.run(["sh", str(repo / "scripts" / "build-repo.sh"), str(cls.tmp / "public")],
                           capture_output=True, text=True, env={**os.environ, "APT_SIGNING_KEY": key})
        assert r.returncode == 0, r.stderr
        cls.public = cls.tmp / "public"
        cls.keyring = cls.public / "test-archive-keyring.gpg"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def verify(self, *extra, keyring=None):
        r = run(sys.executable, VERIFY, self.public, "--keyring", keyring or self.keyring, "--json", "--deep", *extra)
        return r.returncode, json.loads(r.stdout)

    def test_template_builds_a_repository_that_verifies(self):
        code, rep = self.verify(*(["--apt"] if have("apt-get") else []))
        self.assertEqual(code, 0, [c for c in rep["checks"] if not c["ok"]])
        release = (self.public / "dists" / "stable" / "Release").read_text()
        self.assertNotIn(" Release\n", release, "Release must not list itself")

    def test_package_builds_never_see_the_signing_key(self):
        self.assertEqual((self.tmp / "key-seen").read_text(), "")

    def test_keyring_over_plain_http_is_refused(self):
        r = run(sys.executable, VERIFY, self.public, "--keyring", "http://127.0.0.1:9/test-archive-keyring.gpg")
        self.assertEqual(r.returncode, 2)
        self.assertIn("plain http", r.stderr)

    def test_wrong_key_fails_the_signature(self):
        other = self.tmp / "other-gnupg"
        other.mkdir(mode=0o700)
        env = {**os.environ, "GNUPGHOME": str(other)}
        subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-generate-key", "Other <o@example.org>",
                        "ed25519", "sign", "1d"], check=True, capture_output=True, env=env)
        wrong = self.tmp / "wrong.gpg"
        wrong.write_bytes(subprocess.run(["gpg", "--batch", "--export"], check=True, capture_output=True,
                                         env=env).stdout)
        code, rep = self.verify(keyring=wrong)
        self.assertEqual(code, 1)
        self.assertFalse(next(c for c in rep["checks"] if c["check"] == "InRelease signature")["ok"])

    def test_tampered_index_and_pool_are_caught(self):
        tampered = self.tmp / "tampered"
        shutil.copytree(self.public, tampered)
        pkgs = tampered / "dists" / "stable" / "main" / "binary-amd64" / "Packages"
        pkgs.write_text(pkgs.read_text() + "\n")
        deb = next((tampered / "pool" / "main").glob("*.deb"))
        deb.write_bytes(deb.read_bytes() + b"x")
        r = run(sys.executable, VERIFY, tampered, "--keyring", self.keyring, "--json", "--deep")
        failed = [c["check"] for c in json.loads(r.stdout)["checks"] if not c["ok"]]
        self.assertEqual(r.returncode, 1)
        self.assertIn("index main/binary-amd64/Packages", failed)
        self.assertTrue(any("demo 1.0-1" in f for f in failed), failed)


if __name__ == "__main__":
    unittest.main()
