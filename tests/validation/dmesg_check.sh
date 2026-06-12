#!/usr/bin/env bash
set -euo pipefail
if dmesg | grep -Ei "probe failed|call trace|kernel panic"; then
  exit 1
fi

