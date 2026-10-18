#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v xcodegen >/dev/null || {
  echo "Install XcodeGen from its official project: https://github.com/yonaskolb/XcodeGen" >&2
  exit 1
}
"$ROOT/scripts/verify-build-inputs.sh"
xcodegen generate --spec "$ROOT/project.yml" --project "$ROOT"

