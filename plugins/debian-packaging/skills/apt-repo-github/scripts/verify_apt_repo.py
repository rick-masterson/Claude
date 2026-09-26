#!/usr/bin/env python3
"""Verify a published (or local) APT repository the way apt would, and say which link in the chain is broken.

    verify_apt_repo.py BASE_URL_OR_DIR --keyring KEY.gpg [--suite stable] [--deep] [--apt] [--json]

Checks, in order:
  1. dists/<suite>/InRelease exists and its signature verifies against --keyring (gpgv)
  2. every index the Release file lists that is present (Packages, Packages.gz) matches its size and SHA256
  3. every package in each Packages index exists in the pool at the listed size (HEAD); with --deep it is
     downloaded and its SHA256 checked
  4. with --apt: a real `apt-get update` against a throwaway apt state, using only this repo and this keyring,
     then lists the package versions apt now sees. This is what a user's machine will do.

--keyring may be a local path or an https:// URL (e.g. BASE/orac-archive-keyring.gpg); prefer a copy you verified
by fingerprint, because a keyring fetched from the same place as the repo proves nothing on its own. A plain
http:// keyring is refused: it is the trust root, and anyone on the network path could swap it.
Exit 0: all checks pass. 1: something fails. 2: bad usage or unreachable repository. Stdlib + gpgv (+ apt-get).
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


class Source:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.local = not re.match(r"^https?://", base)

    def url(self, rel: str) -> str:
        return f"{self.base}/{rel.lstrip('/')}"

    def get(self, rel: str) -> bytes | None:
        if self.local:
            p = Path(self.base) / rel
            return p.read_bytes() if p.is_file() else None
        try:
            with urllib.request.urlopen(self.url(rel), timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def size(self, rel: str) -> int | None:
        if self.local:
            p = Path(self.base) / rel
            return p.stat().st_size if p.is_file() else None
        req = urllib.request.Request(self.url(rel), method="HEAD")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                n = r.headers.get("Content-Length")
                return int(n) if n is not None else -1
        except urllib.error.HTTPError:
            return None


def stanzas(text: str) -> list[dict]:
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        fields, key = {}, None
        for line in block.splitlines():
            if line[:1] in (" ", "\t") and key:
                fields[key] += "\n" + line.strip()
            elif ":" in line:
                key, _, v = line.partition(":")
                fields[key.strip()] = v.strip()
        if fields:
            out.append(fields)
    return out


def release_body(inrelease: str) -> str:
    """The signed text inside a clearsigned InRelease."""
    m = re.search(r"-----BEGIN PGP SIGNED MESSAGE-----\n(?:Hash:.*\n)*\n(.*?)\n-----BEGIN PGP SIGNATURE-----",
                  inrelease, re.S)
    return m.group(1) if m else inrelease


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Verify an APT repository end to end.")
    ap.add_argument("base", help="repository base URL (https://...) or local directory")
    ap.add_argument("--keyring", required=True, help="binary OpenPGP keyring (path or URL) to verify against")
    ap.add_argument("--suite", default="stable")
    ap.add_argument("--deep", action="store_true", help="download every .deb and check its SHA256")
    ap.add_argument("--apt", action="store_true", help="also run apt-get update against a throwaway apt state")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    src, results = Source(args.base), []
    ok = lambda name, detail="": results.append({"check": name, "ok": True, "detail": detail})
    bad = lambda name, detail: results.append({"check": name, "ok": False, "detail": detail})

    work = Path(tempfile.mkdtemp(prefix="aptverify-"))
    try:
        keyring = work / "keyring.gpg"
        if re.match(r"^http://", args.keyring, re.I):
            print(f"{args.keyring}: refusing a keyring over plain http; use https:// or a local copy verified by "
                  "fingerprint", file=sys.stderr); return 2
        if re.match(r"^https://", args.keyring, re.I):
            data = Source(args.keyring.rsplit("/", 1)[0]).get(args.keyring.rsplit("/", 1)[1])
            if data is None:
                print(f"keyring not found at {args.keyring}", file=sys.stderr); return 2
            keyring.write_bytes(data)
        else:
            if not Path(args.keyring).is_file():
                print(f"{args.keyring}: no such keyring", file=sys.stderr); return 2
            shutil.copy(args.keyring, keyring)
        fpr = subprocess.run(["gpg", "--batch", "--show-keys", "--with-colons", str(keyring)],
                             capture_output=True, text=True).stdout
        fingerprints = re.findall(r"(?m)^fpr:+([0-9A-F]{40}):", fpr)

        dist = f"dists/{args.suite}"
        try:
            inrel = src.get(f"{dist}/InRelease")
        except (urllib.error.URLError, OSError) as e:
            print(f"{args.base}: unreachable: {e}", file=sys.stderr); return 2
        if inrel is None:
            bad("InRelease present", f"{dist}/InRelease not found")
        else:
            ok("InRelease present", f"{len(inrel)} bytes")
            (work / "InRelease").write_bytes(inrel)
            v = subprocess.run(["gpgv", "--keyring", str(keyring), str(work / "InRelease")],
                               capture_output=True, text=True)
            signer = re.search(r"using \S+ key ([0-9A-F]+)", v.stderr)
            (ok if v.returncode == 0 else bad)(
                "InRelease signature", (f"good signature by {signer.group(1) if signer else '?'}"
                                        if v.returncode == 0 else v.stderr.strip().splitlines()[-1]))

            rel = stanzas(release_body(inrel.decode("utf-8", "replace")))[0]
            listed = [l.split() for l in rel.get("SHA256", "").splitlines() if l.strip()]
            packages_indexes = []
            for digest, size, name in listed:
                if name in ("Release", "InRelease", "Release.gpg"):
                    bad("Release lists itself", f"{name} appears in its own hash list: the build redirected "
                        "`apt-ftparchive release dists/<suite>` straight into dists/<suite>/Release, so a partial copy "
                        "was hashed. Write it outside dists/ and move it in. (apt ignores the entry, so installs work.)")
                    continue
                data = src.get(f"{dist}/{name}")
                if data is None:
                    continue  # Release may list variants that are not published (e.g. .xz); apt skips them too
                if len(data) != int(size) or hashlib.sha256(data).hexdigest() != digest:
                    bad(f"index {name}", f"size/SHA256 mismatch (listed {size}, got {len(data)})")
                else:
                    ok(f"index {name}", f"{size} bytes, SHA256 matches")
                    if name.endswith("/Packages"):
                        packages_indexes.append((name, data))
                    elif name.endswith("/Packages.gz"):
                        packages_indexes.append((name, gzip.decompress(data)))
            if not packages_indexes:
                bad("Packages indexes", "the Release file lists no reachable Packages index")

            seen = {}
            for name, data in packages_indexes:
                for p in stanzas(data.decode("utf-8", "replace")):
                    seen[p["Filename"]] = p
            for filename, p in sorted(seen.items()):
                label = f"{p.get('Package')} {p.get('Version')} ({filename})"
                if args.deep:
                    blob = src.get(filename)
                    if blob is None:
                        bad(label, "missing from the pool")
                    elif len(blob) != int(p["Size"]) or hashlib.sha256(blob).hexdigest() != p.get("SHA256"):
                        bad(label, "size/SHA256 mismatch")
                    else:
                        ok(label, "downloaded, SHA256 matches")
                else:
                    n = src.size(filename)
                    if n is None:
                        bad(label, "missing from the pool")
                    elif n not in (-1, int(p["Size"])):
                        bad(label, f"size {n}, index says {p['Size']}")
                    else:
                        ok(label, "present" + ("" if n == -1 else f", {n} bytes"))

        if args.apt and inrel is not None:
            state = work / "apt"
            for d in ("lists/partial", "cache/archives/partial"):
                (state / d).mkdir(parents=True)
            uri = src.base if not src.local else f"file://{Path(src.base).resolve()}"
            (state / "repo.sources").write_text(
                f"Types: deb\nURIs: {uri}/\nSuites: {args.suite}\nComponents: {rel.get('Components', 'main')}\n"
                f"Signed-By: {keyring}\n")
            opts = ["-o", "Dir::Etc::sourcelist=/dev/null", "-o", "Dir::Etc::sourceparts=-",
                    "-o", f"Dir::Etc::SourceList={state / 'repo.sources'}", "-o", f"Dir::State::Lists={state / 'lists'}",
                    "-o", f"Dir::Cache={state / 'cache'}", "-o", "Debug::NoLocking=1", "-o", "APT::Get::List-Cleanup=0"]
            u = subprocess.run(["apt-get", *opts, "update"], capture_output=True, text=True)
            errs = [l for l in (u.stdout + u.stderr).splitlines() if l.startswith(("E:", "W:", "Err:"))]
            if u.returncode or errs:
                bad("apt-get update", " | ".join(errs) or f"exit {u.returncode}")
            else:
                names = sorted({p["Package"] for p in seen.values()}) if 'seen' in dir() else []
                pol = subprocess.run(["apt-cache", *opts, "policy", *names], capture_output=True, text=True).stdout
                cands = re.findall(r"(?m)^(\S+):\n\s+Installed:.*\n\s+Candidate: (\S+)", pol)
                ok("apt-get update", "apt accepted the repository; candidates: "
                   + ", ".join(f"{n} {v}" for n, v in cands))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    passed = all(r["ok"] for r in results)
    if args.json:
        print(json.dumps({"base": args.base, "suite": args.suite, "keyring_fingerprints": fingerprints,
                          "ok": passed, "checks": results}, indent=2))
    else:
        print(f"keyring: {', '.join(fingerprints) or 'no keys found'}")
        for r in results:
            print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['check']}: {r['detail']}")
        print("OK" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
