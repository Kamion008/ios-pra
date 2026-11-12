/* SPDX-License-Identifier: GPL-2.0-only
 * Enter a Linux arm64 Image with the MMU, D-cache and I-cache off.
 * x0 = live DTB physical address, x1 = Image entry physical address.
 *
 * The arm64 boot protocol wants the DTB in x0 and x1..x3 zero; the Image
 * entry is the load address itself (its first instruction is a branch).
 * The loader cleaned the Image and the DTB to the point of coherency before
 * calling this, so dropping the caches here is safe.
 *
 * EL2 was already dropped to EL1 by start.S; Linux boots at EL1 here.
 */
.section .text, "ax"
.global pra_jump_linux
pra_jump_linux:
	msr	daifset, #0xf
	mov	x16, x1			/* Image entry */
	mov	x1, xzr
	mov	x2, xzr
	mov	x3, xzr
	mrs	x14, SCTLR_EL1
	bic	x14, x14, #1		/* M: translation off */
	bic	x14, x14, #4		/* C: D-cache off */
	bic	x14, x14, #0x1000	/* I: I-cache off */
	msr	SCTLR_EL1, x14
	isb
	br	x16
