/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef PRA_CONSOLE_H
#define PRA_CONSOLE_H

#include <stdint.h>
#include <stdarg.h>

void uart_init(void);
void uart_putc(char c);
void uart_puts(const char *s);
void uart_hex64(uint64_t v);
void uart_dec(uint64_t v);

/* Framebuffer text console. base is a physical address, stride in pixels. */
void fb_attach(uintptr_t base, unsigned width, unsigned height, unsigned stride_px);
int  fb_attached(void);
void fb_clear(uint32_t color);
void fb_fill(uintptr_t base, unsigned width, unsigned height,
             unsigned stride_px, uint32_t color);
void fb_fill_range(uintptr_t base, unsigned bytes, uint32_t color);

/* Console output: UART always, framebuffer when attached. */
void con_puts(const char *s);
void con_printf(const char *fmt, ...);
void con_hex(const char *label, uint64_t v);
void con_dec(const char *label, uint64_t v);

#endif
