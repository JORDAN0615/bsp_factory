# CAN bus (SPI-CAN / MCP2518FD) not working on JP7.2 — root cause & workaround

## TL;DR

Getting CAN reliable on MIC-741 / JP7.2 needs **two** things:

1. **Pinmux fix (build-time, necessary):** the MB1 BCT pinmux must have
   `nvidia,enable-input = ENABLE` on the two CAN interrupt pins. JP7.2's regenerated BCT had
   it `DISABLE`, which alone makes CAN completely dead. Already restored in
   `source/modify/driver/bootloader/tegra264-mb1-bct-pinmux-p3834-xxxx-p4071-0000.dtsi`.
2. **Runtime nudge (workaround, necessary):** the CAN interrupt pins are physically held
   LOW, which makes the GPIO interrupt flaky (some boots it gets stuck and CAN never works).
   After bringing CAN up, run a small "nudge" loop (below) to force the interrupt into a
   stable polled state.

The clean long-term fix is hardware (route a real, idle-high MCP2518FD INT pin); the nudge
is a software work-around for the current board.

> Because CAN is **disabled by default for autonomous-driving safety** and only enabled on
> demand, the nudge belongs **inside the CAN-enable command/script** (run right after
> `ip link up`), not in a boot service.

## Hardware background

| Item | Detail |
|------|--------|
| CAN controllers | Two Microchip MCP2518FD (`microchip,mcp251xfd` driver) |
| Interface | SPI (entire data path is over SPI); can0 = spi1.0, can1 = spi0.0 |
| SPI controllers | can0 → `spi@810c590000` (SPI1), can1 → `spi@c6c0000` (SPI2) |
| 40 MHz clock | `clk40m` fixed-clock (identical in 7.1/7.2 — not the problem) |
| Interrupt pins | AON GPIO `PDD.03` / `PDD.04` (`soc_gpio21_pdd3` / `soc_gpio22_pdd4`) |

### Key hardware fact: the INT pins are held LOW (not a real idle-high INT)

`PDD.03` / `PDD.04` are **not wired to the MCP2518FD INT pins as a normal idle-high
interrupt**. On this board they sit **permanently LOW** (verified: `gpioget gpiochip0 21 22`
returns `0 0`, and the level does not follow the pad pull-up/down — it is externally driven
low). The mcp251xfd driver requires an `interrupts` property, so the DT points it at these
pins anyway.

Consequence: a `IRQ_TYPE_LEVEL_LOW` interrupt on a permanently-low line is **always
asserted**, so it storms. See "Why it is flaky" below.

## Part 1 — Pinmux `enable-input` regression (build-time, necessary fix)

The only functional pinmux difference between 7.1 (working) and 7.2 (broken):

`source/modify/driver/bootloader/tegra264-mb1-bct-pinmux-p3834-xxxx-p4071-0000.dtsi`

| pin | property | JP7.1 | JP7.2 (broken) |
|-----|----------|-------|----------------|
| `soc_gpio21_pdd3` (can0 INT) | `nvidia,enable-input` | `ENABLE` | `DISABLE` |
| `soc_gpio22_pdd4` (can1 INT) | `nvidia,enable-input` | `ENABLE` | `DISABLE` |

With `enable-input = DISABLE` the pad input buffer is off, so the SoC cannot even sense the
line → the interrupt can never fire → CAN is 100% dead. Origin: JP7.2 regenerated the BCT
from the new pinmux spreadsheet (`T264_Pinmux_Config_CVM_Jedha_P4070.xlsm`) and reverted the
customized pins to defaults (same class of regression as the I2C3/bus3 timeout case).

Fix — restore `enable-input = ENABLE`, **keep everything else identical to 7.1** (do NOT
change `pull`; `PULL_DOWN` is required so the placeholder pad reads LOW):

```dts
soc_gpio21_pdd3 {
    nvidia,pins = "soc_gpio21_pdd3";
    nvidia,function = "rsvd0";
    nvidia,pull = <TEGRA_PIN_PULL_DOWN>;
    nvidia,tristate = <TEGRA_PIN_ENABLE>;
    nvidia,enable-input = <TEGRA_PIN_ENABLE>;  /* FIX (was DISABLE in JP7.2) */
    nvidia,drv-type = <TEGRA_PIN_1X_DRIVER>;
    nvidia,e-io-od = <TEGRA_PIN_DISABLE>;
    nvidia,e-lpbk = <TEGRA_PIN_DISABLE>;
};
soc_gpio22_pdd4 {
    nvidia,pins = "soc_gpio22_pdd4";
    nvidia,function = "rsvd0";
    nvidia,pull = <TEGRA_PIN_PULL_DOWN>;
    nvidia,tristate = <TEGRA_PIN_ENABLE>;
    nvidia,enable-input = <TEGRA_PIN_ENABLE>;  /* FIX */
    nvidia,drv-type = <TEGRA_PIN_1X_DRIVER>;
    nvidia,e-io-od = <TEGRA_PIN_DISABLE>;
    nvidia,e-lpbk = <TEGRA_PIN_DISABLE>;
};
```

> This pinmux is in the **MB1 BCT (bootloader)**. After editing, **rebuild and reflash the
> bootloader/BCT** (e.g. `advantech/qspi_only.sh` or a full flash). Rebuilding the kernel DTB
> alone does **not** apply it. Verify on target with:
> `sudo busybox devmem 0xc7a3058 32` and `0xc7a3060` → bit 6 (E_INPUT) must read `1`
> (value `0x00203454`).

This fix is **necessary but not sufficient** — with it applied, CAN still behaves flakily
because of the held-low line (Part 2).

## Part 2 — Held-low INT pin → flaky interrupt (the deeper problem)

With `enable-input = ENABLE`, the level-low interrupt on the permanently-low line is always
asserted and **storms**. What happens next is non-deterministic per boot:

- **Good boot:** it storms, the count crosses Linux's spurious threshold (100000), genirq
  auto-disables it (`dmesg`: `irq N: nobody cared, Disabling IRQ`) and then **polls** the
  handler (~10 Hz). mcp251xfd gets serviced → CAN works, CPU idle.
- **Bad boot:** the interrupt gets masked early (e.g. after ~28 fires) and is never
  re-enabled → IRQ count stays low, handler never runs → CAN dead.

Verified by experiment on one cold boot: `/proc/interrupts` count `0`, CAN dead; manually
setting the GPIO interrupt-enable bit kicked the storm and CAN immediately worked. Different
boots give different results — it is genuinely flaky.

Why it cannot be fixed purely in pinmux/DT: the line is held LOW regardless of pull, and the
handler finds no real IC interrupt (the pin is not the IC's INT), so the only "fix" in
software is to force it into the stable storm→disable→poll state — see workaround.

## Workaround — "bounded nudge" inside the CAN-enable command

Run this **after** `ip link set canX up` (the IRQ must already be requested). It re-enables
the GPIO interrupt until the count crosses the spurious threshold on **both** controllers,
which forces genirq to disable+poll → stable. It is **bounded** (stops at the threshold) on
purpose.

```bash
#!/bin/bash
# MIC-741 JP7.2 — enable CAN (on demand) + INT-storm nudge workaround.
# CAN is OFF by default (AD safety); this is the explicit enable command.
set -e

# 1) SPI-CAN I/O expanders / transceivers
for c in "0x74 0x07 0x0f" "0x74 0x03 0xf0" "0x75 0x07 0xfb" "0x75 0x03 0x00"; do
    i2cset -f -y 3 $c
done

# 2) Bring up CAN FD interfaces
for i in 0 1; do
    ip link set can$i down 2>/dev/null || true
    ip link set can$i up type can bitrate 500000 dbitrate 8000000 \
        berr-reporting on fd on loopback off
done

# 3) Nudge the held-low INT GPIO so the storming IRQ crosses the genirq spurious
#    threshold, gets auto-disabled, and settles into poll-recovery mode.
#    Bounded: stops as soon as both lines are past 100k (≈2–12 s, ~10 writes).
#    AON GPIO base 0xcf10000; PDD.03 ENABLE_CONFIG=+0x660, PDD.04=+0x680.
#    0x45 = ENABLE(bit0) | TRIGGER_LEVEL(bit2) | INTERRUPT(bit6).
for n in $(seq 1 60); do
    c1=$(awk '/spi1.0/{print $2}' /proc/interrupts)
    c0=$(awk '/spi0.0/{print $2}' /proc/interrupts)
    [ "${c1:-0}" -gt 100000 ] && [ "${c0:-0}" -gt 100000 ] && break
    busybox devmem 0xcf10660 32 0x45   # AON GPIO PDD.03 (can0 INT)
    busybox devmem 0xcf10680 32 0x45   # AON GPIO PDD.04 (can1 INT)
    sleep 0.2
done
```

### Critical do / don't

- **DO** run the nudge only **after** `ip link up`.
- **DO** keep it **bounded** (stop once both counts > 100000).
  ⚠️ A *continuous* nudge (e.g. re-writing every 20 ms forever) drives an uncontrolled
  storm (~260k irq/s) that hangs the box until the hardware watchdog reboots it.
- **DON'T** use the `irqpoll` kernel cmdline. It "works" but polls *all* IRQs system-wide
  (observed load average ~6, unrelated irq threads at ~50% CPU). The bounded nudge keeps
  CPU ~idle.
- **DON'T** change `pull` to `PULL_UP` — the placeholder pad must read LOW.

## Verification (after the enable command)

```sh
# IRQ should be frozen ~100001 (spurious-disabled into poll mode):
grep -E "spi1.0|spi0.0" /proc/interrupts
# dmesg should show one round of: irq N: nobody cared, Disabling IRQ   (expected, benign)

# Functional test:
sudo candump -t z can1 &
sudo cansend can0 100##7AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
```

Expected after the workaround (validated on fresh boots): slow / fast-burst / sustained /
bidirectional traffic all pass with `dropped=0, errors=0`, and CPU stays ~90%+ idle.

## Proper (long-term) fix — hardware

Route the real MCP2518FD INT pin to a GPIO that **idles HIGH and pulses LOW only on
events**. That removes the permanent assertion, so the interrupt is clean and
deterministic, and both the nudge workaround and the storm/spurious-disable behavior go
away. The pinmux `enable-input = ENABLE` (Part 1) is still required.

## Register reference (T264, SoC-fixed addresses)

| What | Address | Notes |
|------|---------|-------|
| Pad PDD.03 (E_INPUT bit6) | `0xc7a3058` | AON pinmux `0xc7a2000` + `0x1058` |
| Pad PDD.04 | `0xc7a3060` | + `0x1060` |
| GPIO ENABLE_CONFIG PDD.03 | `0xcf10660` | AON gpio `0xcf10000`, bank0/port3, pin3 |
| GPIO ENABLE_CONFIG PDD.04 | `0xcf10680` | pin4. bit0=ENABLE, [3:2]=trigger(1=LEVEL), bit4=level(0=low), bit6=INTERRUPT |
| GPIO INPUT PDD.03 / .04 | `+0x08` | `0xcf10668` / `0xcf10688`, bit0 = line high |

## Related

- Same-class build-time regression (I2C3/bus3 `I2C transfer timed out`): customized pinmux
  pins reverted by the regenerated JP7.2 BCT.
- A per-pin 7.1↔7.2 pinmux audit also flagged SPI3/TPM (`spi3_*` → rsvd1 + input disabled,
  `dmesg`: `tpm_tis_spi: probe of spi2.0 failed -110`) and others (UART9, UFS0,
  extperiph1–4, PWM2/3) — verify against actual MIC-741 usage before restoring.
- DT node: `source/modify/kernel/hardware/nvidia/t264/nv-public/nv-platform/tegra264-p4071-0000.dtsi`
  (`spi@810c590000` / `spi@c6c0000` / `clk40m`).
