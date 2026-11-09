/* SPDX-License-Identifier: GPL-2.0-only
 * Linked so that the decompressed arm64 Image lands at the stock
 * kernel_addr (0x480000 = RAM base 0x400000 + text_offset 0x80000).
 */
ENTRY(_start)
SECTIONS
{
    . = 0x480000;
    .text : {
        KEEP(*(.text.head))
        *(.text*)
    }
    .rodata : { *(.rodata*) }
    .data   : { *(.data*) }
    . = ALIGN(4096);
    _image_end = .;

    __bss_start = .;
    .bss : {
        *(.bss*)
        *(COMMON)
    }
    . = ALIGN(4096);
    __bss_end = .;

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
