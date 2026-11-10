/* SPDX-License-Identifier: GPL-2.0-only
 * Enter the XNU kernel with the MMU, D-cache and I-cache off, DAIF masked.
 * x0 = entry physical address, x1 = boot_args physical address.
 *
 * The loader copied every segment and cleaned it to the point of coherency,
 * so dropping the caches here is safe. XNU's start.S expects the state the
 * bootloader hands it: translation off, physical == virtual.
 */
.section .text, "ax"
.global pra_jump_mmu_off
pra_jump_mmu_off:
	msr	daifset, #0xf
	mov	x16, x0			/* entry */
	mov	x0, x1			/* XNU wants boot_args in x0 */
	mrs	x14, SCTLR_EL1
	bic	x14, x14, #1		/* M: translation off */
	bic	x14, x14, #4		/* C: D-cache off */
	bic	x14, x14, #0x1000	/* I: I-cache off */
	msr	SCTLR_EL1, x14
	isb
	br	x16
