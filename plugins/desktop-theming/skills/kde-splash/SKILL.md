---
name: kde-splash
description: Create, fix, preview or package a KDE Plasma login splash (KSplash QML, Splash.qml) or a Plasma look-and-feel / global theme package. Use when the user mentions the KDE/Plasma splash screen, the screen shown after login, a Splash.qml, a look-and-feel or global theme, or says a custom splash "doesn't show" or "falls back to the default".
---

# KDE Plasma KSplash themes

A KSplash that fails to load shows no error at login: Plasma silently skips it. So **load it before you install
it, and look at it**.

## 1. Load and screenshot it offscreen

```bash
python3 scripts/render_splash.py <Splash.qml | contents/splash/ | look-and-feel dir> [--stage N] [--size 1920x1080] [--out splash.png] [--json]
```

Exit 0 means it loaded and the screenshot was written, 1 means QML errors (the splash would not show), 2 means bad
usage, and 3 means PyQt6/QtQuick is missing (Debian: `python3-pyqt6` plus the `qml6-module-qtquick*` packages).

- It prints the exact `file:line` of every QML error, and collects runtime warnings too.
- Unresolved `i18n*()` calls are expected: ksplash injects KDE's translation functions at login, and this
  preview doesn't.
- **Open the PNG and look at it.** Loading cleanly is not the same as looking right.
- Try `--stage 1` and a high stage to see the start and end of the progress UI.

It is a preview with no ksplash host. For the real thing on a live desktop:
`ksplashqml --test --window <look-and-feel-dir>`.

## 2. Facts that trip people up (checked against Plasma 6.7 and its Breeze splash)

- **`stage`:** ksplash sets an integer `stage` property **on the root object** and raises it as the session starts.
  Declare `property int stage` on the root; Breeze animates at `stage == 2` and `stage == 5`. Don't write
  `onStageChanged: root.stage = stage` (it assigns the property to itself). Bind to it instead:
  `opacity: index < root.stage - 1 ? 1 : pulse`.
- **Colours are `#AARRGGBB`**, alpha first. `"#000000AA"` is fully transparent dark blue, not a translucent black.
  Translucent black is `"#AA000000"`.
- **`letterSpacing` belongs to the font**: `font.letterSpacing: 2`. A bare `letterSpacing:` on a `Text` is an
  unknown property, and one unknown property stops the entire splash loading.
- **Animated values vs bindings:** an `Animation on opacity` overrides a binding on `opacity`. Animate a custom
  property (`property real pulse`) and bind `opacity` to it.
- **Size:** ksplash sizes the root to the screen. Anchor to `parent`; don't rely on a fixed `width: 1920`.
- **Fonts:** name one family per `font.family` (`"JetBrains Mono"`), not a CSS-style list. Check it is installed
  with `fc-list | grep -i "<family>"`.

## 3. Package layout (look-and-feel)

```
<id>/metadata.desktop  (or metadata.json)   X-KDE-PluginInfo-Name=<id>, X-KDE-ServiceTypes=Plasma/LookAndFeel
<id>/contents/splash/Splash.qml             + images/ it references
<id>/contents/previews/splash.png           (400x225 preview in System Settings)
<id>/contents/defaults                      optional: the settings applied by "Global Theme" (ksplashrc Theme=<id>, colours, wallpaper...)
```

- **System-wide:** `/usr/share/plasma/look-and-feel/<id>/`. **Per user:** `~/.local/share/plasma/look-and-feel/<id>/`.
- Choose it in **System Settings → Splash Screen** (splash only) or **Global Theme** (everything in `defaults`).
  Applying a global theme replaces the user's colours, icons and cursor. Say so before recommending it.
- Plasma 6 accepts both `metadata.desktop` (older, still used by e.g. Shadowfetch) and `metadata.json` (Breeze).
- A package installs files; it must never switch the user's theme itself. Leave selection to the user.
