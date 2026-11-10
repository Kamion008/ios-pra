/* SPDX-License-Identifier: GPL-2.0-only
 * PRA XNU loader. Linked at the stock kernel load address like the
 * diagnostic shim, so the bootloader can decompress and run it unchanged.
 *
 * The SWEETXNU payload is appended to the flat image at the fixed physical
 * address __payload_start (0x500000). The loader is far smaller than the
 * 512 KiB between 0x480000 and 0x500000, so a fixed address keeps the
 * payload pointer a link-time constant with no relocation.
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

/* Absolute symbol, outside SECTIONS so it does not extend the binary. */
__payload_start = 0x500000;
