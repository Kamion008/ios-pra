/* SPDX-License-Identifier: GPL-2.0-only
 * Link the handoff test payload at the start of the PRA XNU window.
 */
ENTRY(test_entry)
SECTIONS
{
    . = 0x88000000;
    .text : { *(.text*) }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    . = ALIGN(4096);
    .bss : { *(.bss*) *(COMMON) }
    . = ALIGN(4096);
    __payload_end = .;

    /DISCARD/ : {
        *(.note*)
        *(.comment*)
        *(.eh_frame*)
        *(.interp*)
        *(.dynamic*)
        *(.dynsym*)
        *(.dynstr*)
        *(.gnu.*)
    }
}
