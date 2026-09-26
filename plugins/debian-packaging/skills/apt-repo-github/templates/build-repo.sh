#!/bin/sh
# Build every package under packages/ and lay out a signed APT repository in $1 (default: public/).
#
#   APT_SIGNING_KEY   ASCII-armored private key (the GitHub Actions secret). Without it the
#                     repository is built UNSIGNED, which apt refuses -- only for local checks.
#
# Layout (what apt fetches):
#   dists/stable/{Release,InRelease,Release.gpg}
#   dists/stable/main/binary-{amd64,all}/Packages{,.gz}
#   pool/main/*.deb
#   @NAME@-archive-keyring.gpg   public key for /etc/apt/keyrings
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
out=$(mkdir -p "${1:-$root/public}" && cd "${1:-$root/public}" && pwd)
suite=stable

rm -rf "$out/dists" "$out/pool"
mkdir -p "$out/pool/main"
# Package builds never see the signing key: a build script, or anything it runs, could otherwise copy it.
for build in "$root"/packages/*/build.sh; do
    (unset APT_SIGNING_KEY; sh "$build" "$out/pool/main")
done

cd "$out"
for arch in amd64 all; do
    dir=dists/$suite/main/binary-$arch
    mkdir -p "$dir"
    apt-ftparchive packages pool/main > "$dir/Packages"
    gzip -9n -c "$dir/Packages" > "$dir/Packages.gz"
done

# Write Release OUTSIDE dists/ and move it in: `> dists/$suite/Release` creates the file before apt-ftparchive hashes
# the directory, so the Release listed a partial copy of itself (found by verify_apt_repo.py, 2026-09-25).
apt-ftparchive \
    -o APT::FTPArchive::Release::Origin=@ORIGIN@ \
    -o APT::FTPArchive::Release::Label=@ORIGIN@ \
    -o APT::FTPArchive::Release::Suite=$suite \
    -o APT::FTPArchive::Release::Codename=$suite \
    -o "APT::FTPArchive::Release::Architectures=amd64 all" \
    -o APT::FTPArchive::Release::Components=main \
    -o "APT::FTPArchive::Release::Description=@DESCRIPTION@" \
    release "dists/$suite" > "$out/Release.tmp"
mv "$out/Release.tmp" "dists/$suite/Release"

if [ -z "${APT_SIGNING_KEY:-}" ]; then
    echo "build-repo: APT_SIGNING_KEY not set -- repository is UNSIGNED (local check only)" >&2
    exit 0
fi

GNUPGHOME=$(mktemp -d)
export GNUPGHOME
trap 'rm -rf "$GNUPGHOME"' EXIT
printf '%s\n' "$APT_SIGNING_KEY" | gpg --batch --quiet --import
fpr=$(gpg --batch --with-colons --list-secret-keys | awk -F: '/^fpr:/{print $10; exit}')
gpg --batch --yes --local-user "$fpr" --clearsign -o "dists/$suite/InRelease" "dists/$suite/Release"
gpg --batch --yes --local-user "$fpr" --armor --detach-sign -o "dists/$suite/Release.gpg" "dists/$suite/Release"
gpg --batch --yes --export "$fpr" > @NAME@-archive-keyring.gpg
gpg --batch --yes --armor --export "$fpr" > @NAME@-archive-keyring.asc

# Fail the publish rather than ship something apt would reject.
gpgv --keyring ./@NAME@-archive-keyring.gpg "dists/$suite/InRelease"
echo "build-repo: signed with $fpr"
