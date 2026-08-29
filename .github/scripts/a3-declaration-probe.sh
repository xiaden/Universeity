#!/usr/bin/env sh
# a3-declaration-probe.sh
#
# A3' (optional, diagnostic-only): ONE hosted client.workflows.list() probe with NO
# prefix filter; exact-match canonical umd-<stage> names client-side. Written to
# a3-declaration-probe.txt and NEVER gates the release — a declaration/list probe
# alone is never release proof (engine-visible-proof.txt is the only authoritative
# gate). Runs under `if: always()` and exits 0 even on SDK/schema failure so a
# diagnostic probe can never fail the job.
set -eu

python3 - "$HATCHET_TENANT_TOKEN" > a3-declaration-probe.txt 2>&1 <<'PY' || rc=$?
import os, sys
from urllib.parse import urlparse

stages = (
    "ingest format_analysis basic_segmentation low_level_extraction "
    "structural_analysis entity_resolution cross_source_alignment "
    "semantic_reconciliation current_search_projection"
).split()
canonical = sorted({f"umd-{s}" for s in stages})
token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("UMD_HATCHET_TOKEN", "")

print("A3'-PROBE (DIAGNOSTIC ONLY, NON-AUTHORITATIVE — never release proof)")
try:
    import hatchet_sdk
    server_url = os.environ["UMD_HATCHET_SERVER_URL"]
    host = urlparse(server_url).hostname or "127.0.0.1"
    port = os.environ.get("UMD_HATCHET_CLIENT_HOST_PORT", "7070")
    cfg = hatchet_sdk.ClientConfig(token=token, host_port=f"{host}:{port}")
    declared = [w.name for w in hatchet_sdk.Hatchet(config=cfg).workflows.list()]
    matched = sorted(set(declared) & set(canonical))
    missing = [c for c in canonical if c not in declared]
    print("workflows.list() count:", len(declared))
    print("exact umd-<stage> declared:", matched)
    print("missing canonical:", missing)
    print("NOTE: engine rows + live callback evidence (engine-visible-proof) is the only release proof")
except Exception as exc:  # diagnostic-only: record, never fail
    print("A3'-PROBE ERROR (non-authoritative, recorded only):", repr(exc))
    rc=0
PY
echo "A3'-PROBE exit=${rc:-0} (diagnostic only; does not gate the release)"
exit 0
