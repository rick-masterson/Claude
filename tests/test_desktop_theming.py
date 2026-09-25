"""Tests for the desktop-theming plugin's scripts, run against small fixtures in tests/fixtures/.

Three of the "good" fixture's lines are false positives an earlier version of the checker raised. Each was
disproved against Plymouth's source and against the stock themes that boot on Debian:
- the SetMessageFunction alias (defined in script-lib-plymouth.script)
- a global reassigned inside a function (script-execute.c resolves local -> this -> global)
- Image("special://logo"), a built-in image rather than a theme file
"""
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
SKILLS = ROOT / "plugins" / "desktop-theming" / "skills"
CHECKER = SKILLS / "plymouth-theme" / "scripts" / "check_plymouth_theme.py"
RENDERER = SKILLS / "kde-splash" / "scripts" / "render_splash.py"


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)


class PlymouthChecker(unittest.TestCase):
    def report(self, target, *flags):
        r = run(CHECKER, target, "--json", *flags)
        return r.returncode, json.loads(r.stdout)

    def messages(self, report, level):
        return [i["message"] for i in report["issues"] if i["level"] == level]

    def test_real_api_passes_including_former_false_positives(self):
        code, rep = self.report(FIX / "plymouth-good")
        self.assertEqual(code, 0, rep)
        self.assertEqual(self.messages(rep, "error") + self.messages(rep, "warning"), [])

    def test_each_defect_is_reported(self):
        code, rep = self.report(FIX / "plymouth-bad")
        self.assertEqual(code, 1)
        errors = " | ".join(self.messages(rep, "error"))
        for needle in ("Plymouth.GetTime does not exist", "SetScale(): Sprites cannot scale",
                       'Image("background.png"): no such file', "missing.script"):
            self.assertIn(needle, errors)
        self.assertTrue(any("prompt_sprite" in w for w in self.messages(rep, "warning")))
        self.assertTrue(any("plymouth-label" in i for i in self.messages(rep, "info")))

    def test_strict_turns_warnings_into_failure(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            only_warning = Path(d, "w.script")  # a local sprite and nothing else wrong
            only_warning.write_text("fun cb(p, b) {\n    s = Sprite();\n}\nPlymouth.SetDisplayPasswordFunction(cb);\n")
            self.assertEqual(run(CHECKER, only_warning).returncode, 0)
            self.assertEqual(run(CHECKER, only_warning, "--strict").returncode, 1)

    def test_bad_usage_exits_2(self):
        self.assertEqual(run(CHECKER, FIX / "does-not-exist").returncode, 2)

    def test_comments_are_ignored(self):
        spec = importlib.util.spec_from_file_location("chk", CHECKER)
        chk = importlib.util.module_from_spec(spec); spec.loader.exec_module(chk)
        code = chk.strip_comments('a = 1; # Plymouth.GetTime()\n// x.SetScale(1)\n/* Plymouth.Nope */ b = "#not";\n')
        self.assertNotIn("GetTime", code); self.assertNotIn("SetScale", code); self.assertNotIn("Nope", code)
        self.assertIn('"#not"', code)
        self.assertEqual(code.count("\n"), 3)


def have_pyqt6_quick():
    try:
        import PyQt6.QtQuick  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(have_pyqt6_quick(), "PyQt6 with QtQuick is not installed")
class SplashRenderer(unittest.TestCase):
    def test_good_splash_loads_and_writes_a_screenshot(self):
        out = ROOT / "tests" / "_render_good.png"
        try:
            r = run(RENDERER, FIX / "splash-good", "--json", "--wait", "200", "--out", out)
            rep = json.loads(r.stdout)
            self.assertEqual(r.returncode, 0, rep)
            self.assertTrue(out.is_file() and out.stat().st_size > 0)
        finally:
            out.unlink(missing_ok=True)

    def test_unknown_property_fails_with_its_line(self):
        r = run(RENDERER, FIX / "splash-bad", "--json")
        rep = json.loads(r.stdout)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any("letterSpacing" in e and ":10:" in e for e in rep["errors"]), rep["errors"])


class RendererUsage(unittest.TestCase):
    def test_missing_qml_exits_2(self):
        self.assertEqual(run(RENDERER, FIX / "plymouth-good").returncode, 2)


if __name__ == "__main__":
    unittest.main()
