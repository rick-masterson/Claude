#!/usr/bin/env python3
"""Load a KDE Plasma KSplash QML file offscreen, report every QML error, and save a screenshot.

    render_splash.py SPLASH_QML_OR_LNF_DIR [--stage N] [--size 1920x1080] [--wait MS] [--out splash.png] [--json]

Accepts the Splash.qml itself, its contents/splash/ directory, or a whole look-and-feel package directory.
Exit 0: loaded without errors and screenshot written. Exit 1: QML errors (the splash would not show at login).
Exit 2: bad usage. Exit 3: PyQt6 with QtQuick is not installed (pip/apt: python3-pyqt6 + qml6 modules).

Why offscreen: a KSplash that fails to load does not show an error at login. Plasma silently skips it. Loading it
here surfaces the exact file:line, and the PNG lets an agent (or you) look at the result without logging out.
It is a preview, not the real thing: it has no ksplash host, so `stage` only changes if you pass --stage. For the
real check on a desktop, run: ksplashqml --test --window <look-and-feel-dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def find_qml(target: Path) -> Path | None:
    for candidate in (target, target / "Splash.qml", target / "contents" / "splash" / "Splash.qml"):
        if candidate.is_file() and candidate.suffix == ".qml":
            return candidate
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Load a KSplash QML offscreen, report errors, save a screenshot.")
    ap.add_argument("target", type=Path)
    ap.add_argument("--stage", type=int, default=3, help="value to set on the root `stage` property (default 3)")
    ap.add_argument("--size", default="1920x1080", help="WIDTHxHEIGHT (default 1920x1080)")
    ap.add_argument("--wait", type=int, default=1500, help="ms to let animations run before the screenshot")
    ap.add_argument("--out", type=Path, default=Path("splash-render.png"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    qml = find_qml(args.target)
    if qml is None:
        print(f"{args.target}: no Splash.qml found", file=sys.stderr)
        return 2
    try:
        w, h = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        print(f"--size {args.size!r}: expected WIDTHxHEIGHT", file=sys.stderr)
        return 2

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt6.QtCore import QSize, QTimer, QUrl
        from PyQt6.QtGui import QGuiApplication
        from PyQt6.QtQuick import QQuickView
    except ImportError as exc:
        print(f"PyQt6 with QtQuick is required: {exc}", file=sys.stderr)
        return 3

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    view = QQuickView()
    runtime: list[str] = []
    view.engine().warnings.connect(lambda ws: runtime.extend(w.toString() for w in ws))
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(QSize(w, h))
    view.setSource(QUrl.fromLocalFile(str(qml.resolve())))
    errors = [e.toString() for e in view.errors()]
    result = {"qml": str(qml), "ok": not errors, "errors": errors, "screenshot": None, "stage": args.stage}

    if not errors and view.rootObject() is not None:
        root = view.rootObject()
        if root.property("stage") is not None:
            root.setProperty("stage", args.stage)
        else:
            result["note"] = "root object has no `stage` property; KSplash sets it on the root, so progress UI " \
                             "keyed to stage will never move"
        view.show()

        def grab():
            view.grabWindow().save(str(args.out))
            result["screenshot"] = str(args.out.resolve())
            app.quit()

        QTimer.singleShot(args.wait, grab)
        app.exec()

    # Runtime warnings: the splash loaded, but something inside it misbehaved. KSplash injects KDE's i18n functions
    # (i18n, i18nc, i18nd, i18ndc, ...) into the real login splash, so their absence here is expected, not a defect.
    host_provided = [w for w in runtime if "ReferenceError: i18n" in w]
    result["runtime_warnings"] = [w for w in runtime if w not in host_provided]
    result["host_provided"] = host_provided

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for e in errors:
            print(f"ERROR {e}")
        for w in result["runtime_warnings"]:
            print(f"WARN  {w}")
        if host_provided:
            print(f"INFO  {len(host_provided)} i18n call(s) unresolved here; ksplash provides them at login")
        if result.get("note"):
            print(f"NOTE  {result['note']}")
        print(f"{'OK' if result['ok'] else 'FAIL'}: {qml}"
              + (f" -> {result['screenshot']}" if result["screenshot"] else ""))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
