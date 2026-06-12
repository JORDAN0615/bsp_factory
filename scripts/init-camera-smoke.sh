#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

AGENT="${BSP_AGENT_BIN:-.venv/bin/bsp-agent}"
REPO="${BSP_AGENT_SMOKE_REPO:-/tmp/bsp-agent-init-camera-smoke-repo}"
LOG="${BSP_AGENT_SMOKE_LOG:-tests/fixtures/sample_dmesg_imx219_regulator_fail.txt}"
ISSUE="${BSP_AGENT_SMOKE_ISSUE:-After flashing custom Orin NX BSP, imx219 camera probe fails with i2c -121 and missing camera regulator}"

if [[ ! -x "$AGENT" ]]; then
  echo "error: bsp-agent executable not found: $AGENT" >&2
  echo "hint: run from repo root after installing the project, or set BSP_AGENT_BIN." >&2
  exit 1
fi

if [[ ! -f "$LOG" ]]; then
  echo "error: fixture log not found: $LOG" >&2
  exit 1
fi

if [[ -e "$REPO" && ! -f "$REPO/.bsp-agent-smoke-repo" ]]; then
  echo "error: refusing to overwrite non-smoke repo: $REPO" >&2
  echo "hint: set BSP_AGENT_SMOKE_REPO to another path, or remove that directory yourself." >&2
  exit 1
fi

rm -rf "$REPO"
mkdir -p "$REPO/arch/arm64/boot/dts/nvidia"
mkdir -p "$REPO/arch/arm64/configs"
mkdir -p "$REPO/drivers/media/i2c"
touch "$REPO/.bsp-agent-smoke-repo"

cat > "$REPO/arch/arm64/boot/dts/nvidia/tegra234-p3767-camera-imx219.dtsi" <<'EOF'
/ {
    i2c@3180000 {
        imx219_a@10 {
            compatible = "sony,imx219";
            reg = <0x10>;
            status = "disabled";
            reset-gpios = <&tegra_main_gpio 0 0>;
        };
    };
};
EOF

cat > "$REPO/arch/arm64/boot/dts/nvidia/tegra234-p3767-regulators.dtsi" <<'EOF'
/ {
    fixed-regulators {
        cam_iovdd: regulator-cam-iovdd {
            compatible = "regulator-fixed";
            regulator-name = "cam_iovdd";
            regulator-min-microvolt = <1800000>;
            regulator-max-microvolt = <1800000>;
        };
    };
};
EOF

cat > "$REPO/arch/arm64/boot/dts/nvidia/tegra234-p3767-camera-overlay.dts" <<'EOF'
/dts-v1/;
/plugin/;

/ {
    overlay-name = "p3767 imx219 camera";
};
EOF

cat > "$REPO/arch/arm64/configs/p3767_camera_defconfig" <<'EOF'
CONFIG_VIDEO_IMX219=m
CONFIG_I2C_TEGRA=y
EOF

cat > "$REPO/drivers/media/i2c/imx219_board_check.c" <<'EOF'
// Minimal fixture file for BSP agent smoke testing.
int imx219_board_check(void)
{
    return 0;
}
EOF

git -C "$REPO" init -q
git -C "$REPO" add .
git -C "$REPO" -c user.name="BSP Agent Smoke" -c user.email="bsp-agent-smoke@example.invalid" commit -q -m "Create camera smoke BSP fixture"

echo "== BSP Agent init-run smoke =="
echo "Repo:  $REPO"
echo "Issue: $ISSUE"
echo "Log:   $LOG"
echo

if [[ "${BSP_AGENT_INTERACTIVE:-0}" == "1" ]]; then
  "$AGENT" init-run \
    --repo "$REPO" \
    --issue "$ISSUE" \
    --log "$LOG" \
    "$@"
else
  "$AGENT" init-run \
    --no-interactive \
    --repo "$REPO" \
    --issue "$ISSUE" \
    --log "$LOG" \
    "$@"
fi
