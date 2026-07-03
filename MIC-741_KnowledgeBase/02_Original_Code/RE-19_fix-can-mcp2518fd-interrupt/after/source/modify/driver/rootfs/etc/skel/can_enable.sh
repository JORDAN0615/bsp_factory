#!/bin/bash
#
# can_enable.sh — MIC-741 (JP7.2 / T264) on-demand CAN enable
#
# CAN is OFF by default for autonomous-driving safety; this script is the
# explicit enable command. It:
#   1. configures the SPI-CAN I/O expanders / transceivers
#   2. brings up can0 / can1 as CAN-FD
#   3. applies the "INT-storm nudge" workaround
#
# Why the nudge: the MCP2518FD interrupt pins (AON GPIO PDD.03/PDD.04) are held
# LOW on this board, so the level-low IRQ is permanently asserted and storms.
# Some boots leave it stuck-masked and CAN never works. Nudging re-enables the
# GPIO interrupt until the count crosses the genirq spurious threshold (100000)
# on both controllers; genirq then auto-disables it and polls the handler,
# which is the stable working state (CPU stays idle).
#
# NOTE: This is a software work-around for a hardware issue (the INT line is not
# a real idle-high INT). The proper fix is to route a real idle-high MCP2518FD
# INT pin in hardware. Also requires the MB1 BCT pinmux fix (enable-input=ENABLE
# on soc_gpio21_pdd3 / soc_gpio22_pdd4); see docs/can-bus-pinmux-interrupt.md.
#
# Usage: sudo ./can_enable.sh
#
set -u

# --- config ---------------------------------------------------------------
I2C_BUS=3
BITRATE=500000
DBITRATE=8000000
IFACES="can0 can1"

# AON GPIO ENABLE_CONFIG registers (T264, SoC-fixed):
#   base 0xcf10000, port DD = bank0/port3 -> +0x600, pin*0x20
#   PDD.03 (can0 INT) = 0xcf10660, PDD.04 (can1 INT) = 0xcf10680
# value 0x45 = ENABLE(bit0) | TRIGGER_LEVEL(bit2) | INTERRUPT(bit6)
NUDGE_REGS="0xcf10660 0xcf10680"
NUDGE_VAL=0x45
NUDGE_THRESH=100000     # genirq spurious-disable threshold
NUDGE_MAX_ITERS=60      # bounded: ~12 s worst case (must NOT loop forever)
NUDGE_SLEEP=0.2
# --------------------------------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
    echo "[can_enable] must run as root (use sudo)" >&2
    exit 1
fi

echo "[can_enable] 1/3 configuring SPI-CAN I/O expanders on i2c-${I2C_BUS}"
i2cset -f -y "$I2C_BUS" 0x74 0x07 0x0f
i2cset -f -y "$I2C_BUS" 0x74 0x03 0xf0
i2cset -f -y "$I2C_BUS" 0x75 0x07 0xfb
i2cset -f -y "$I2C_BUS" 0x75 0x03 0x00

echo "[can_enable] 2/3 bringing up: ${IFACES}"
for ifc in $IFACES; do
    ip link set "$ifc" down 2>/dev/null || true
    ip link set "$ifc" up type can \
        bitrate "$BITRATE" dbitrate "$DBITRATE" \
        berr-reporting on fd on loopback off
done

echo "[can_enable] 3/3 nudging held-low INT GPIO into stable polled state"
reached=0
for n in $(seq 1 "$NUDGE_MAX_ITERS"); do
    c1=$(awk '/spi1.0/{print $2}' /proc/interrupts)
    c0=$(awk '/spi0.0/{print $2}' /proc/interrupts)
    if [ "${c1:-0}" -gt "$NUDGE_THRESH" ] && [ "${c0:-0}" -gt "$NUDGE_THRESH" ]; then
        echo "[can_enable]   storm threshold reached (iter ${n}, spi1.0=${c1} spi0.0=${c0})"
        reached=1
        break
    fi
    for r in $NUDGE_REGS; do busybox devmem "$r" 32 "$NUDGE_VAL"; done
    sleep "$NUDGE_SLEEP"
done
[ "$reached" -eq 1 ] || echo "[can_enable]   WARNING: threshold not reached after ${NUDGE_MAX_ITERS} iters; CAN may be unreliable"

echo "[can_enable] done. quick status:"
for ifc in $IFACES; do
    state=$(ip -br link show "$ifc" 2>/dev/null | awk '{print $2}')
    echo "  ${ifc}: ${state}"
done
echo "  (test: 'candump can1 &' then 'cansend can0 100##7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')"
