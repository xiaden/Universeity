#!/usr/bin/env sh
# record-release-summary.sh <compose_file>
#
# P2-S6 release evidence: append the actually-pulled image digests (built image,
# db, hatchet, base) and the optional-provider gate table to the GitHub Actions
# step summary ($GITHUB_STEP_SUMMARY). Digests are recorded with
# `docker image inspect --format '{{index .RepoDigests 0}}'` so the release gate
# has concrete image provenance; gated providers stay visible with their reason.
set -eu

compose_file="${1:?usage: record-release-summary.sh <compose_file>}"
summary="${GITHUB_STEP_SUMMARY:-}"

if [ -z "$summary" ] || [ ! -w "$summary" ]; then
  echo "[record-release-summary] GITHUB_STEP_SUMMARY unavailable; skipping summary" >&2
  exit 0
fi

# P3-S5: the live-worker-gate verdict (PASS/FAIL). Absent marker = FAIL.
# The workflow writes this file only on a genuinely-passing live run; a live-job
# failure or an unconditional skip leaves it absent/failed, and the summary shows
# FAIL. This is a required release gate, never a warning.
live_gate="$(cat live-worker-gate.txt 2>/dev/null || echo FAIL)"

{
  echo ""
  echo "## UMD live-worker release gate"
  echo ""
  echo "| Gate | Verdict |"
  echo "| --- | --- |"
  echo "| live-worker-gate | $live_gate |"
  echo ""
  echo "> A live-worker-gate of FAIL means the sole-v1-scheduler did not perform real"
  echo "> registered work (worker never became ready, a live job failed, or a mandatory"
  echo "> live test was skipped). This is release-blocking, not a warning."
} >> "$summary"

# P3-S3: machine-readable hosted engine-visible verdicts. Every row below is a
# release-blocking signal; a missing verdict (absent tenant-identity.txt or
# engine-verdicts.txt, or an engine-visible-proof FAIL) fails the release gate.
{
  echo ""
  echo "## UMD hosted engine-visible verdicts (P3-S3, machine-readable)"
  echo ""
  echo "| Verdict | Value |"
  echo "| --- | --- |"
  if [ -f tenant-identity.txt ]; then
    echo "| eligible-tenant | $(sed -n 's/^tenant_id: /OK:/p' tenant-identity.txt | tr -d '[:space:]' | head -n1) |"
    echo "| tenant-schema | $(sed -n 's/^schema: /OK:/p' tenant-identity.txt | tr -d '[:space:]' | head -n1) |"
    echo "| tenant-table | $(sed -n 's/^table: /OK:/p' tenant-identity.txt | tr -d '[:space:]' | head -n1) |"
    echo "| scheduler-partition | $(sed -n 's/^scheduler_partition_id: /OK:/p' tenant-identity.txt | tr -d '[:space:]' | head -n1) |"
    echo "| worker-partition | $(sed -n 's/^worker_partition_id: /OK:/p' tenant-identity.txt | tr -d '[:space:]' | head -n1) |"
  else
    echo "| eligible-tenant | FAIL (missing tenant-identity.txt) |"
  fi
  if [ -f engine-verdicts.txt ]; then
    while IFS='=' read -r k v; do
      [ -z "$k" ] && continue
      printf '| %s | %s |\n' "$k" "$v"
    done < engine-verdicts.txt
  else
    echo "| engine-visible-proof | FAIL (missing engine-verdicts.txt) |"
  fi
  echo "| live-worker-gate | $live_gate |"
  echo ""
  echo "> tenant-identity + engine-verdicts rows are the hosted proof that the repaired"
  echo "> durable direct-input worker was assigned, ran durably, wrote callback-owned rows,"
  echo "> and all under one scheduler-eligible tenant. Missing verdict = release-blocking."
} >> "$summary"

{
  echo ""
  echo "## UMD Release evidence - image digests"
  echo ""
  echo "| Image | Digest |"
  echo "| --- | --- |"
  # Every image the resolved compose graph references (built image, db, hatchet).
  docker compose -f "$compose_file" config --images 2>/dev/null | sort -u | while read -r name; do
    [ -z "$name" ] && continue
    digest="$(docker image inspect --format '{{if index .RepoDigests 0}}{{index .RepoDigests 0}}{{else}}<no repo digest> (local build: {{.Id}}){{end}}' "$name" 2>/dev/null || echo "unavailable")"
    printf '| %s | %s |\n' "$name" "$digest"
  done
  # P3-S4: exact-image preflight digests (all 4 split Hatchet images at the pinned tag).
  if [ -f image-digests.txt ]; then
    echo ""
    echo "## UMD Hatchet split-image preflight (exact tag)"
    echo ""
    echo '| Image reference | Manifest digest | Result |'
    echo '| --- | --- | --- |'
    while read -r ref d result; do
      [ -z "$ref" ] && continue
      printf '| %s | %s | %s |\n' "$ref" "${d:-unavailable}" "${result:-OK}"
    done < image-digests.txt
  fi
  base="python:3.13-slim"
  bd="$(docker image inspect --format '{{if index .RepoDigests 0}}{{index .RepoDigests 0}}{{else}}<no repo digest>{{end}}' "$base" 2>/dev/null || echo "unavailable")"
  printf '| %s (Dockerfile base) | %s |\n' "$base" "$bd"
} >> "$summary"

{
  echo ""
  echo "## UMD optional-provider gates (CI)"
  echo ""
  echo "| Provider | Status | Gate reason |"
  echo "| --- | --- | --- |"
  echo "| sandbox-runner (\`sandbox\` profile) | ENABLED | Required decompose-isolation profile; non-privileged (read-only root, cap_drop ALL, seccomp) |"
  echo "| ollama (\`gpu\` profile) | GATED (disabled) | GPU host + model provisioning required; optional profile not enabled in CI |"
  echo "| minio / \`s3bridge\` profile | GATED (disabled) | Optional S3-compatible OCFL substrate; filesystem OCFL volume used in CI |"
} >> "$summary"

echo "[record-release-summary] appended image digests + provider gates to step summary"
