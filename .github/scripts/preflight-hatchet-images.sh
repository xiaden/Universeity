#!/usr/bin/env sh
# preflight-hatchet-images.sh <hatchet_version>
#
# P3-S4 exact-image preflight: BEFORE any Compose startup, verify that EVERY split
# Hatchet image exists at the EXACT pinned tag on ghcr.io and capture its manifest
# reference + digest + the candidate-pin outcome. A denied / nonexistent image
# (like the historical top-level `ghcr.io/hatchet-dev/hatchet` reference, which is
# 403-denied on ghcr.io) FAILS this step — it must never reach `docker compose up`.
#
# This is a hosted-runner helper validated statically (sh -n) here and proven at
# runtime by GitHub Actions. Uses the native engine manifest surface (no image
# pull, no Docker socket mount).
#
# Output: writes one line per image to `image-digests.txt` in the current dir:
#   <reference> <manifest-digest-or-unavailable> <OK|DENIED>
# and prints the candidate pin outcome for the release summary.
set -eu

version="${1:?usage: preflight-hatchet-images.sh <hatchet_version (e.g. v0.105.2)>}"

out="${IMAGE_DIGESTS_FILE:-image-digests.txt}"
: > "$out"

ok=1
for img in hatchet-migrate hatchet-admin hatchet-engine hatchet-dashboard; do
  ref="ghcr.io/hatchet-dev/hatchet/${img}:${version}"
  printf 'preflight %s ... ' "$ref"
  digest="$(docker buildx imagetools inspect "$ref" --format '{{json .Manifest.Digest}}' 2>/dev/null \
        || docker manifest inspect "$ref" >/dev/null 2>&1 \
        || true)"
  if [ -z "$digest" ]; then
    printf 'DENIED/nonexistent -> FAIL\n' >&2
    printf '%s unavailable DENIED\n' "$ref" >> "$out"
    ok=0
  else
    printf 'OK (manifest %s)\n' "$digest"
    printf '%s %s OK\n' "$ref" "$digest" >> "$out"
  fi
done

if [ "$ok" -ne 1 ]; then
  echo "image preflight FAILED: at least one split Hatchet image is not pullable at ${version}" >&2
  cat "$out" >&2 || true
  exit 1
fi

echo "image preflight PASS for all 4 split Hatchet images at ${version} (candidate pair, pending live validation)"
echo "candidate-pin-outcome: all split images present at ${version}" >> "$out"
