---
name: apt-repo-github
description: Publish your own signed APT repository from a GitHub repo (built and signed in GitHub Actions, served by GitHub Pages) so machines get your .deb packages through apt update/upgrade, or verify/debug an existing APT repository. Use when the user wants their own update channel, a PPA-like repo, "distribute my packages with apt", an add-on repo layered on a distro, or apt complains about a repository (signature, NO_PUBKEY, hash sum mismatch, 404).
---

# Your own signed APT repository on GitHub

This works for a **remix**: add-on packages layered on an existing distro, which keeps supplying the base system and
its own updates. It does not make you a distro maintainer.

## 1. Verify any repository, before and after every change

```bash
python3 scripts/verify_apt_repo.py https://OWNER.github.io/REPO --keyring /etc/apt/keyrings/NAME-archive-keyring.gpg --apt [--deep]
```

It checks, in order, and names the link that broke:
1. the InRelease signature, against the keyring you pass;
2. every index's size and SHA256;
3. every package in the pool (`--deep` downloads and hashes them);
4. with `--apt`, a real `apt-get update` in a throwaway apt state.

Pass a keyring you verified **by fingerprint**. One fetched from the same site as the repo proves nothing on its
own, and one fetched over plain `http://` is refused. It works on a local directory too, so check before you push.
Exit codes: 0 ok, 1 failure, 2 unreachable or refused.

## 2. Set one up (templates in `templates/`)

- **Repository:** `packages/<name>/build.sh` writes one `.deb` into its `$1`. `templates/build-repo.sh` (fill in
  `@NAME@`, `@ORIGIN@` and `@DESCRIPTION@`) builds every package, writes `dists/stable/main/binary-{amd64,all}/Packages`
  and signs `InRelease` and `Release.gpg`.
- **CI:** `templates/publish.yml` goes in `.github/workflows/`. On a push to `main` it runs the tests, builds, signs
  and deploys to Pages. It fails if the signing secret is missing.
- **The repo must be public**: free-plan Pages only serves public repos, and apt cannot log in. Anything in it can
  be downloaded by anyone. Ask the user before publishing, and keep private work in a separate private repo.
- **Signing key:** `gpg --batch --passphrase '' --quick-generate-key "NAME APT signing key <email>" ed25519 sign 3y`.
  Store the armored private key as the Actions secret `APT_SIGNING_KEY`
  (`gpg --armor --export-secret-keys FPR | gh secret set APT_SIGNING_KEY --repo OWNER/REPO`). The user's `~/.gnupg`
  is the backup. **Never commit a private key.** Record the fingerprint and the expiry date in the repo's docs.
- **Pages:** `gh api -X POST repos/OWNER/REPO/pages -f build_type=workflow`. On a brand-new repo this returns 404
  until the first push; the Actions secret endpoint can 404 for a few seconds too. Retry.

## 3. Client setup (give these to the user; they need sudo)

```bash
sudo curl -fsSLo /etc/apt/keyrings/NAME-archive-keyring.gpg https://OWNER.github.io/REPO/NAME-archive-keyring.gpg
gpg --show-keys /etc/apt/keyrings/NAME-archive-keyring.gpg    # compare the fingerprint with the one you published
printf 'Types: deb\nURIs: https://OWNER.github.io/REPO/\nSuites: stable\nComponents: main\nSigned-By: /etc/apt/keyrings/NAME-archive-keyring.gpg\n' | sudo tee /etc/apt/sources.list.d/NAME.sources
sudo apt update
```

Use `Signed-By`, scoped to this repo, never `apt-key` or `trusted.gpg.d`: a key trusted globally could sign
packages for *any* repository.

## 4. Traps (each one happened)

- **`apt-ftparchive release dists/X > dists/X/Release`** lists a partial copy of Release inside itself. The shell
  creates the file before it is hashed. Write to a temp file outside `dists/` and move it in (the template does).
- **An upgrade already running ignores a repo added mid-run.** `apt upgrade` computes its package list at the start;
  run `apt update` again after adding a source.
- **`git push` → "Repository not found"** while `gh` works: git is using a different stored credential. Push with
  `git -c credential.helper= -c "credential.helper=!gh auth git-credential" push`.
- **Nothing upgrades:** the `Version:` was not bumped. apt only installs a higher version.
- **Duplicate-source warnings** ("configured multiple times"): two files describe the same repo. Delete the one no
  package manages; a package-managed `.list` comes back on its next update.
