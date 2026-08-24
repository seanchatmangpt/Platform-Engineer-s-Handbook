#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROD="$(cd "${HERE}/.." && pwd)"
MARKETPLACE="${GGEN_MARKETPLACE_DIR:-${PROD}/ggen-marketplace}"
LOCK="${HERE}/marketplace.lock.json"
GGEN_BIN="${GGEN_BIN:-${1:-}}"
[[ -n "${GGEN_BIN}" && -x "${GGEN_BIN}" ]] || { echo "REFUSED:GGEN_BINARY_REQUIRED" >&2; exit 2; }
[[ -d "${MARKETPLACE}/.git" ]] || { echo "REFUSED:MARKETPLACE_CHECKOUT_REQUIRED:${MARKETPLACE}" >&2; exit 2; }
expected_marketplace="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["marketplace"]["commit"])' "${LOCK}")"
actual_marketplace="$(git -C "${MARKETPLACE}" rev-parse HEAD)"
[[ "${actual_marketplace}" == "${expected_marketplace}" ]] || { echo "REFUSED:MARKETPLACE_COMMIT_DRIFT:actual=${actual_marketplace}:expected=${expected_marketplace}" >&2; exit 3; }
python3 "${MARKETPLACE}/scripts/marketplace.py" validate >/dev/null
python3 "${HERE}/build_domain.py"
rm -rf "${PROD}/generated" "${PROD}/docs" "${PROD}/src/gdmcp"
rm -f "${PROD}/runtime/generated_platform.py" "${PROD}/runtime/dfcm_generated.py"
( cd "${PROD}" && "${GGEN_BIN}" sync run )

DFCM="${MARKETPLACE}/packs/dfcm-pack"
rm -rf "${DFCM}/consumer"
( cd "${DFCM}" && "${GGEN_BIN}" sync run )
[[ -f "${DFCM}/consumer/dfcm/runtime.py" ]] || { echo "REFUSED:DFCM_RUNTIME_NOT_GENERATED" >&2; exit 4; }
mkdir -p "${PROD}/runtime" "${PROD}/generated/dfcm"
cp -R "${DFCM}/consumer/dfcm/." "${PROD}/generated/dfcm/"
cp "${DFCM}/consumer/dfcm/runtime.py" "${PROD}/runtime/dfcm_generated.py"
( cd "${PROD}/generated/dfcm" && python3 verify.py )

# Construct provider deployment graphs independently. This is CONSTRUCT only:
# bblock writes plans, pack locks, local directories, and receipts; it never
# calls a cloud API or acquires platform DO authority.
for provider in aws gcp; do
  root="${PROD}/generated/deployment/${provider}"
  mkdir -p "${root}"
  ( cd "${root}" && \
    "${GGEN_BIN}" bblock validate && \
    "${GGEN_BIN}" bblock plan --group-id fortune5-complete --provider "${provider}" && \
    "${GGEN_BIN}" bblock enable --group-id fortune5-complete --provider "${provider}" )
done
python3 "${HERE}/verify_generated.py"
