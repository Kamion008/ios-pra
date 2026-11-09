/* SPDX-License-Identifier: GPL-2.0-only
 * Huawei PRA-LX1 (hi6250 / Kirin 655) diagnostic entry.
 *
 * Entered by the Huawei bootloader with MMU off, x0 = live DTB physical
 * address. The image is linked at the stock kernel load address (0x480000).
 * Everything here is read-only except the two known-safe display candidates
 * and the UART; no storage write, no clock or pin reconfiguration.
 */
.section .text.head, "ax"
.global _start
_start:
	b	entry
	.long	0
	.quad	0x80000			/* text_offset from RAM base 0x400000 */
	.quad	0			/* image_size, filled by the linker script check */
	.quad	0			/* flags */
	.quad	0, 0, 0
	.byte	0x41, 0x52, 0x4d, 0x64	/* "ARMd" */
	.long	0

entry:
	msr	daifset, #0xf
	mov	x19, x0			/* live DTB */
	mrs	x20, CurrentEL
	and	x20, x20, #0xc
	cmp	x20, #0x8		/* EL2? */
	b.eq	el2_to_el1

el1_entry:
	/* 128 KiB of stack below the image is not available; use the image's
	 * own .bss stack, which the linker places after .data. */
	adr	x0, pra_stack_top
	mov	sp, x0

	/* Clear .bss without assuming it is zero. */
	adr	x0, __bss_start
	adr	x1, __bss_end
1:	cmp	x0, x1
	b.hs	2f
	str	xzr, [x0], #8
	b	1b
2:
	mov	x0, x19			/* DTB */
	bl	pra_main
3:	wfe
	b	3b

el2_to_el1:
	/* HCR_EL2.RW=1: EL1 is AArch64. Allow EL1 access to the counters. */
	mov	x0, #(1 << 31)
	msr	HCR_EL2, x0
	isb
	mov	x0, #3
	msr	CNTHCTL_EL2, x0
	isb
	adr	x0, el1_entry
	msr	ELR_EL2, x0
	mov	x0, #0x3c5		/* EL1h, DAIF masked */
	msr	SPSR_EL2, x0
	eret

	.ltorg

.section .bss, "aw", %nobits
.balign 16
pra_stack:
	.space 65536
pra_stack_top:
