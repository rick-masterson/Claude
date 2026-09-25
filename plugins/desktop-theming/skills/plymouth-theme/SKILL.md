---
name: plymouth-theme
description: Create, fix, review or package a Plymouth boot splash (script-module themes, .plymouth + .script files) on Debian/Ubuntu-family Linux. Use when the user mentions a boot splash, Plymouth, the boot screen, a boot animation or progress bar, the LUKS/encrypted-disk unlock prompt at boot, or hands over a Plymouth theme to install or debug ("my splash doesn't animate", "boot screen shows text instead", "make a boot theme").
---

# Plymouth script themes

Plymouth shows nothing when a theme script is wrong. The splash just stops animating, drops elements, or falls
back to text, and you only see it at the next boot. So **never trust a theme by reading it: run the checker**, and
test the theme without rebooting.

## 1. Check the theme first

```bash
python3 scripts/check_plymouth_theme.py <theme-dir-or-.script> [--json] [--strict]
```

Exit 0 means no errors, 1 means errors, 2 means bad usage. `--json` gives machine-readable output for other tools
and agents. Fix every ERROR. Read every WARNING. The checker's API lists come from Plymouth's source, not memory, and
every stock theme on a Debian machine passes it.

## 2. The API facts that trip people up (verified against Plymouth's source)

- **A Sprite cannot scale.** There is no `Sprite.SetScale`. Scale the *image* and set it again:
  `sprite.SetImage(img.Scale(w, h))`. For a progress bar, keep the source image and `Scale(width * progress, h)`
  when the progress changes, not on every frame.
- **There is no clock.** `Plymouth.GetTime` does not exist. Count ticks in the refresh callback for animations.
  It runs at 50 frames per second by default (`FRAMES_PER_SECOND` in plugin.c); `Plymouth.SetRefreshRate(n)`
  changes it.
- **Sprite methods:** `SetImage/GetImage`, `SetX/Y/Z`, `GetX/Y/Z`, `SetOpacity/GetOpacity`, `SetPosition(x, y, z)`.
- **Callbacks:** `Plymouth.SetBootProgressFunction(fun(duration, progress))` (progress is 0..1),
  `SetRefreshFunction`, `SetDisplayMessageFunction(fun(text))` + `SetHideMessageFunction`,
  `SetDisplayPasswordFunction(fun(prompt, bullets))`, `SetDisplayPromptFunction(fun(prompt, entry, is_secret))`,
  `SetDisplayNormalFunction`, `SetSystemUpdateFunction(fun(progress))` (0..100), `SetQuitFunction`.
  `SetMessageFunction` is an old alias of `SetDisplayMessageFunction`; prefer the new name.
- **Scoping:** a bare name resolves local, then `this`, then global. Assigning to an existing global inside a
  function updates it. A name that exists nowhere becomes a **local**, and a sprite held only in a local is freed
  and **disappears when the function returns**. Create sprites at top level, or store them in a global object
  (`password.bullets[i].sprite = Sprite(img)`).
- **Text:** `Image.Text(text, r, g, b, a, "Sans Bold 14")` needs a text renderer plugin in the initramfs
  (Debian/Ubuntu: package `plymouth-label`).
- **Screen size:** use `Window.GetWidth()/GetHeight()/GetX()/GetY()`. Scale the background once to *cover* the
  screen, never per frame.
- **Math:** `Math.Int`, `Math.Min/Max/Clamp/Abs`, `Math.Sin/Cos/Tan/ATan2/Sqrt`, `Math.Pi`, `Math.Random`.

## 3. Install, select, test (Debian family)

- A theme lives in `/usr/share/plymouth/themes/<name>/`, with `<name>.plymouth` naming `ModuleName=script`,
  `ImageDir` and `ScriptFile` by their **installed** paths.
- **Selecting it:** `sudo plymouth-set-default-theme -R <name>`. It is in `/usr/sbin`, and `-R` rebuilds the
  initramfs. This writes `Theme=` in `/etc/plymouth/plymouthd.conf`, and that setting wins over the
  `default.plymouth` alternative. Some distros (e.g. Shadowfetch) select the theme only this way, so a package must
  **not** register itself as a `default.plymouth` alternative: with no other candidate it silently becomes the
  default.
- **Is it in the boot image?**
  `sudo lsinitramfs /boot/initrd.img-$(uname -r) | grep -E "themes/<name>/|label-pango"`. The initrd is root-only;
  a non-root listing returns nothing, which does not mean the theme is missing.
- **Preview without rebooting** (it takes over the display):
  ```bash
  sudo plymouthd --debug --debug-file=/tmp/plymouth.log && sudo plymouth --show-splash
  for i in $(seq 0 100); do sudo plymouth system-update --progress=$i; sleep 0.03; done
  sudo plymouth display-message --text="hello"; sleep 3; sudo plymouth --quit
  ```
  `plymouth --update=` sends a status string, not progress. Script errors land in `/tmp/plymouth.log`.
- **Needs root:** everything above except the checker. If you are an agent without root, give the user the exact
  commands and read the results back; never ask for their password.

## 4. Packaging

Ship the theme as its own package (`/usr/share/plymouth/themes/<name>/`). Depend on `plymouth` and
`plymouth-label`, and leave activation to the user (`plymouth-set-default-theme -R`). If the theme is already
active on upgrade, run `update-initramfs -u` in postinst so the boot image does not keep the old copy.
