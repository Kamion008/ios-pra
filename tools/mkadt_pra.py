#!/usr/bin/env python3
"""Build an entry-only PRA-LX1 (hi6250 / Kirin 655) ADT from the donor's minimal schema.

This carries the Kirin 655 GICv2 distributor/CPU-interface window and the
eMMC MMIO window for a read-only GPT probe. It is not yet an iOS root/device
tree.

Hardware facts come from the live PRA-LX1 boot (see PRA-LX1_PROGRESS.md):
timer at 1.92 MHz, 8x Cortex-A53 in two clusters of four (MPIDR 0..3 and
0x100..0x103), PL011 at 0xFDF02000, GIC at 0xE82B1000/0xE82B2000.

XNU's pe_arm_get_soc_base_phys() takes the *parent* base from /arm-io "ranges"
cell 1, and every /arm-io child "reg" is an offset from that base. The parent
window here is 0xE0000000..0x100000000, so the child regs are written relative
to it (0x82B1000 -> 0xE82B1000, 0x1DF02000 -> 0xFDF02000). The root-level fbcon
is different: fbcon_probe() calls ml_io_map_wcomb(reg[0], reg[1]) with no soc
offset, so pra-fbcon stays absolute. pra-emmc follows the SoC-relative
convention used by the arm-io children.
"""
import argparse
import os
from pathlib import Path

import adt
import mkadt


# Kirin 655 SoC MMIO window: pe_arm_get_soc_base_phys() returns ranges cell 1,
# and the arm-io children publish offsets from it.
SOC_BASE = 0xE0000000
SOC_SIZE = 0x20000000
TIMEBASE = 1920000          # dmesg: "Architected cp15 timer(s) running at 1.92MHz"
CORTEX_A53 = 1700000000     # live DT clock-frequency of the four 1.7 GHz A53s
CORTEX_A53_HI = 2100000000  # live DT clock-frequency of the 0x100..0x103 cluster


def set_prop(node, name, value):
    for i, (key, flags, _) in enumerate(node.props):
        if key == name:
            node.props[i] = (key, flags, value)
            return
    node.props.append((name, 0, value))


def child(node, name):
    for candidate in node.children:
        if candidate.prop('name') == mkadt.cstr(name):
            return candidate
    raise ValueError(f'missing donor ADT node {name}')


def build():
    root = mkadt.build(seed=os.urandom(64), qemu=True)
    set_prop(root, 'compatible', mkadt.cstr('hisilicon,hi6250') +
             mkadt.cstr('AppleARM'))
    chosen = child(root, 'chosen')
    buttons = child(root, 'buttons')
    # PRA-LX1 has no Home button, so MobileGestalt gets a home-button-less class.
    # The three names below are the only keys this port can see, and the GPIO
    # addresses behind them (amba/gpio@e8a0b000..) are UNVERIFIED: no live
    # evidence yet ties volup/voldown/hold to a specific GPIO slot.
    set_prop(buttons, 'home-button-type', mkadt.u32(1))
    set_prop(buttons, 'button-names', b''.join(mkadt.cstr(name) for name in
                                               ('volup', 'voldown', 'hold')))
    set_prop(chosen, 'dram-base', mkadt.u64(0x80000000))
    set_prop(chosen, 'dram-size', mkadt.u64(0x60000000))
    set_prop(chosen, 'firmware-version', mkadt.cstr('pra-hi6250-entry'))
    set_prop(chosen, 'system-firmware-version', mkadt.cstr('pra-hi6250-entry'))
    cpus = child(root, 'cpus')
    cpu0 = child(cpus, 'cpu0')
    set_prop(cpu0, 'compatible', mkadt.cstr('arm,cortex-a53') +
             mkadt.cstr('ARM,v8'))
    set_prop(cpu0, 'reg', mkadt.u32(0x000))
    set_prop(cpu0, 'state', mkadt.cstr('running'))
    set_prop(cpu0, 'timebase-frequency', mkadt.u32(TIMEBASE))
    set_prop(cpu0, 'clock-frequency', mkadt.u32(CORTEX_A53))
    set_prop(cpu0, 'bus-frequency', mkadt.u32(100000000))
    set_prop(cpu0, 'memory-frequency', mkadt.u32(933000000))
    set_prop(cpu0, 'peripheral-frequency', mkadt.u32(TIMEBASE))
    set_prop(cpu0, 'fixed-frequency', mkadt.u32(TIMEBASE))
    set_prop(cpu0, 'cluster-id', mkadt.u32(0))
    set_prop(cpu0, 'cluster-type', mkadt.u32(0))
    set_prop(cpu0, 'die-cluster-id', mkadt.u32(0))
    set_prop(cpu0, 'cluster-core-id', mkadt.u32(0))
    set_prop(cpu0, 'l2-cache-id', mkadt.u32(0))
    set_prop(cpu0, 'l3-cache-id', mkadt.u32(0))
    # Huawei's live hi6250 DT has two A53 clusters of four cores: MPIDR 0..3 in
    # cluster 0 and 0x100..0x103 in cluster 1, i.e. cluster = (mpidr >> 8) & 0xff
    # and core = mpidr & 0xff. The given 1.7 GHz / 2.1 GHz clock-frequency cells
    # match the live cpufreq utargets 1709000 kHz and 2112000 kHz in dmesg, so
    # the rounded values stand in here. Logical order walks the low cluster first,
    # so the cpus=N boot arg still selects a valid prefix.
    for logical in range(1, 8):
        cluster, core = divmod(logical, 4)
        mpidr = (cluster << 8) | core
        cpus.children.append(mkadt.node(f'cpu{logical}', [
            ('device_type', mkadt.cstr('cpu')),
            ('compatible', mkadt.cstr('arm,cortex-a53') + mkadt.cstr('ARM,v8')),
            ('reg', mkadt.u32(mpidr)),
            ('cpu-id', mkadt.u32(logical)),
            ('cluster-id', mkadt.u32(cluster)),
            ('cluster-type', mkadt.u32(0)),
            ('die-cluster-id', mkadt.u32(cluster)),
            ('cluster-core-id', mkadt.u32(core)),
            ('l2-cache-id', mkadt.u32(cluster)),
            ('l3-cache-id', mkadt.u32(0)),
            ('state', mkadt.cstr('stopped')),
            ('timebase-frequency', mkadt.u32(TIMEBASE)),
            ('clock-frequency', mkadt.u32(CORTEX_A53_HI if cluster else CORTEX_A53)),
            ('bus-frequency', mkadt.u32(100000000)),
            ('memory-frequency', mkadt.u32(933000000)),
            ('peripheral-frequency', mkadt.u32(TIMEBASE)),
            ('fixed-frequency', mkadt.u32(TIMEBASE)),
        ]))
    arm_io = child(root, 'arm-io')
    set_prop(arm_io, 'device_type', mkadt.cstr('pra-io'))
    set_prop(arm_io, 'compatible', mkadt.cstr('hisilicon,hi6250-io') +
             mkadt.cstr('arm-io'))
    set_prop(arm_io, 'ranges', mkadt.u64(0, SOC_BASE, SOC_SIZE))
    arm_io.children = [n for n in arm_io.children if n.prop('name') ==
                       mkadt.cstr('wdt')]
    # Kirin 655 has a GICv2 distributor plus banked CPU interface, not GICv3.
    # The live DTB/hisiap puts the pair at 0xE82B1000 and 0xE82B2000 (live dmesg
    # reports "gic" at reg_base 0xe82b0000 size 0x2000). pe_fiq.c maps soc + r[0]
    # and soc + r[2], so the published cells are offsets from SOC_BASE:
    # 0xE0000000 + 0x82B1000 = 0xE82B1000, + 0x82B2000 = 0xE82B2000.
    arm_io.children.append(mkadt.node('gic', [
        ('compatible', mkadt.cstr('arm,cortex-a15-gic')),
        ('interrupt-controller', mkadt.cstr('master')),
        ('virtual-timer-intid', mkadt.u32(27)),
        ('reg', mkadt.u64(0x82B1000, 0x1000, 0x82B2000, 0x1000)),
    ]))
    # The live hisifb0/DSS handoff already scans out a 1080x1920 panel; publish
    # its iOS display service without importing the SWEET panel size.
    arm_io.children.append(mkadt.node('disp0', [
        ('device_type', mkadt.cstr('display-subsystem')),
        ('compatible', mkadt.cstr('hisilicon,hi6250-display')),
        ('canvas-width', mkadt.u32(1080)),
        ('canvas-height', mkadt.u32(1920)),
    ]))
    # /amba/uart@fdf02000 in the live iomem map: the PL011 XNU's VMAPPLE_UART
    # path maps from soc_base. interrupt 74 is the live DT's IRQ cell, kept for
    # reference only (the in-kernel driver polls; nothing reads it today).
    arm_io.children.append(mkadt.node('uart0', [
        ('compatible', mkadt.cstr('arm,pl011') + mkadt.cstr('arm,primecell')),
        ('reg', mkadt.u64(0x1DF02000, 0x1000)),
        ('interrupt', mkadt.u32(74)),
    ]))
    root.children = [n for n in root.children if n.prop('name') not in
                     (mkadt.cstr('sweet-fbcon'), mkadt.cstr('sweet-ufs'))]
    # fbcon_probe() maps exactly reg[1] bytes through ml_io_map_wcomb(), and
    # io_map() before STARTUP_SUB_KMEM advances virtual_space_start by that
    # size. arm_vm_init() only pre-allocates L3 tables for
    # Video.v_height * v_rowBytes, so the node must declare one screen, not
    # the whole 48 MiB logo window. The diagnostic shim can still flood the
    # window; XNU only needs 1080*1920*4 = 0x7E9000 bytes.
    root.children.append(mkadt.node('pra-fbcon', [
        ('reg', mkadt.u64(0x5D000000, 1080 * 1920 * 4)),
        ('width', mkadt.u32(1080)),
        ('height', mkadt.u32(1920)),
        ('stride', mkadt.u32(4320)),
    ]))
    # Live iomem "ff390000-ff39ffff : mmc0", the block host the GPT probe reads.
    # Written as the 0xE0000000 SoC-relative offset per the SoC-base convention.
    # Caveat: the donor's b-s-d dev host driver (a5xelte-emmc-c) maps its own
    # root-level node with ml_io_map(reg[0], reg[1]) and no soc offset, so a PRA
    # driver that reuses that pattern must publish the absolute 0xFF390000 instead.
    root.children.append(mkadt.node('pra-emmc', [
        ('reg', mkadt.u64(0x1F390000, 0x10000)),
    ]))
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    blob = adt.serialize(build())
    args.output.write_bytes(blob)
    print(f'{args.output}: {len(blob)} bytes')
