#!/usr/bin/env bash
#
# build_bsp.sh — the BSP build entrypoint the agent calls (ADR-0018).
#
# It does two things on the Ubuntu build host:
#   1. GLUE: copy the agent's patched overlay repo into the framework_ria
#      project scaffold. The overlay repo mirrors the destination tree, so a
#      whole-folder copy places every file at the right path (see ADR-0018):
#        <repo>/config  -> <project>/source/config
#        <repo>/kernel  -> <project>/source/modify/kernel
#        <repo>/driver  -> <project>/source/modify/driver
#   2. BUILD: run the framework_ria pipeline (make -f main.mk), which applies
#      source/modify onto the build tree and cross-compiles it in Docker.
#
# Contract the agent depends on (do not break):
#   usage:  build_bsp.sh <SRC_DIR> [BUILD_SCOPE]
#   exit 0        -> build succeeded
#   exit non-zero -> build failed (this is the gate signal)
#   stdout+stderr -> the build log the agent captures verbatim
#
# The framework project (downloaded NV sources, Docker base image, source/raw,
# per-project hooks) must already be prepared on this host — this script only
# refreshes the customization overlay and (re)builds. See ADR-0018 setup runbook.

set -euo pipefail

SRC_DIR="${1:?usage: build_bsp.sh <patched-overlay-repo> [build-scope]}"
BUILD_SCOPE="${2:-full}"

# --- Build-host configuration (export these on the Ubuntu workstation) --------
: "${FRAMEWORK_RIA_DIR:?set FRAMEWORK_RIA_DIR to your framework_ria checkout}"
: "${FRAMEWORK_PROJECT_DIR:?set FRAMEWORK_PROJECT_DIR to the prepared framework project}"

SRC_DIR="$(cd "$SRC_DIR" && pwd)"
FRAMEWORK_RIA_DIR="$(cd "$FRAMEWORK_RIA_DIR" && pwd)"
FRAMEWORK_PROJECT_DIR="$(cd "$FRAMEWORK_PROJECT_DIR" && pwd)"

log() { echo "[build_bsp] $*"; }

# --- 1. GLUE: overlay repo -> framework project scaffold ----------------------
sync_overlay() {
    local dst_config="$FRAMEWORK_PROJECT_DIR/source/config"
    local dst_modify="$FRAMEWORK_PROJECT_DIR/source/modify"
    mkdir -p "$dst_config" "$dst_modify"

    if [ -d "$SRC_DIR/config" ]; then
        log "sync config -> source/config"
        cp -a "$SRC_DIR/config/." "$dst_config/"
    fi
    # Every overlay top-level dir except config mirrors the source tree and lands
    # under source/modify/<name>/... at its identical relative path.
    local top
    for top in kernel driver; do
        if [ -d "$SRC_DIR/$top" ]; then
            log "sync $top -> source/modify/$top"
            rm -rf "${dst_modify:?}/$top"
            cp -a "$SRC_DIR/$top" "$dst_modify/$top"
        fi
    done
}

# --- 2. BUILD: run the framework_ria pipeline ---------------------------------
run_framework_build() {
    log "framework build (scope=$BUILD_SCOPE) project=$FRAMEWORK_PROJECT_DIR"
    cd "$FRAMEWORK_PROJECT_DIR"
    # main.mk drives the whole pipeline off framework= and project=. On a
    # prepared project the init/prepare/base phase markers already exist, so
    # `all` re-runs only the build phase (recover -> modify -> kernel_dtb -> ...).
    #
    # BUILD_SCOPE is reserved: narrowing to a dtb-only gate maps to config.mk
    # is_build_* flags / a lighter target and must be confirmed on the host
    # against framework_ria before it is wired here. Until then the project's
    # config.mk settings decide what gets built.
    make -f "$FRAMEWORK_RIA_DIR/main.mk" all \
        framework="$FRAMEWORK_RIA_DIR" \
        project="$FRAMEWORK_PROJECT_DIR"
}

main() {
    log "src=$SRC_DIR"
    sync_overlay
    run_framework_build
    log "build OK"
}

main "$@"
