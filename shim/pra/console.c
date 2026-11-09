/* SPDX-License-Identifier: GPL-2.0-only
 * PL011 UART at 0xFDF02000 (19.2 MHz reference) and up to two linear
 * framebuffer text consoles (for colour-coded scanout identification).
 * All polled MMIO; nothing here uses interrupts.
 */
#include <stdint.h>
#include <stdarg.h>
#include "console.h"
#include "../font.h"

#define UART_BASE 0xFDF02000UL

#define UART_DR   0x00
#define UART_FR   0x18
#define UART_IBRD 0x24
#define UART_FBRD 0x28
#define UART_LCR  0x2c
#define UART_CR   0x30
#define UART_IMSC 0x38
#define UART_ICR  0x44

static inline uint32_t rd32(uintptr_t a) { return *(volatile uint32_t *)a; }
static inline void wr32(uintptr_t a, uint32_t v) { *(volatile uint32_t *)a = v; }

/* The screen is the only output we can observe. The bootloader may gate the
 * PL011 clock at handoff; in that case FR reads all-ones and every character
 * spins uart_wait() a million times, stalling the diagnostic before it ever
 * reaches the framebuffer. Keep the code for a future UART cable, but leave
 * output disabled by default. */
static volatile int uart_ok;

static void uart_wait(void)
{
	for (unsigned i = 0; i < 1000000; i++) {
		if (!(rd32(UART_BASE + UART_FR) & (1u << 5)))
			return;
	}
}

void uart_init(void)
{
	uart_ok = 0;
}

void uart_putc(char c)
{
	if (!uart_ok)
		return;
	if (c == '\n')
		uart_putc('\r');
	uart_wait();
	wr32(UART_BASE + UART_DR, (uint8_t)c);
}

void uart_puts(const char *s) { while (*s) uart_putc(*s++); }

void uart_hex64(uint64_t v)
{
	uart_puts("0x");
	for (int i = 15; i >= 0; i--) {
		unsigned d = (v >> (i * 4)) & 0xf;
		uart_putc(d < 10 ? '0' + d : 'a' + d - 10);
	}
}

void uart_dec(uint64_t v)
{
	char buf[24];
	int n = 0;
	if (!v) { uart_putc('0'); return; }
	while (v && n < (int)sizeof(buf)) { buf[n++] = '0' + (v % 10); v /= 10; }
	while (n) uart_putc(buf[--n]);
}

/* ---- framebuffers ----------------------------------------------------- */

struct fb {
	uintptr_t base;
	unsigned w, h, stride;
	unsigned col, row;
};
static struct fb fbs[2];
static int nfb;

int fb_attached(void) { return nfb != 0; }

void fb_attach(uintptr_t base, unsigned width, unsigned height, unsigned stride_px)
{
	if (!base || nfb >= 2)
		return;
	fbs[nfb].base = base;
	fbs[nfb].w = width;
	fbs[nfb].h = height;
	fbs[nfb].stride = stride_px;
	fbs[nfb].col = fbs[nfb].row = 0;
	nfb++;
}

void fb_fill(uintptr_t base, unsigned width, unsigned height,
             unsigned stride_px, uint32_t color)
{
	for (unsigned y = 0; y < height; y++) {
		volatile uint32_t *line = (volatile uint32_t *)(base + (uintptr_t)y * stride_px * 4);
		for (unsigned x = 0; x < width; x++)
			line[x] = color;
	}
}

/* Fill a byte range as 32-bit pixels; used to flood whole carveouts. */
void fb_fill_range(uintptr_t base, unsigned bytes, uint32_t color)
{
	volatile uint32_t *p = (volatile uint32_t *)base;
	for (unsigned i = 0; i < bytes / 4; i++)
		p[i] = color;
}

static void fb_clear_one(struct fb *f, uint32_t color)
{
	for (unsigned y = 0; y < f->h; y++) {
		volatile uint32_t *line = (volatile uint32_t *)(f->base + (uintptr_t)y * f->stride * 4);
		for (unsigned x = 0; x < f->w; x++)
			line[x] = color;
	}
	f->col = f->row = 0;
}

void fb_clear(uint32_t color)
{
	for (int i = 0; i < nfb; i++)
		fb_clear_one(&fbs[i], color);
}

static void fb_glyph_one(struct fb *f, char c)
{
	unsigned idx = (unsigned char)c;
	if (idx < 32 || idx > 126)
		idx = '?';
	const unsigned char *g = font8x16[idx - 32];

	if (c == '\n') {
		f->col = 0;
		f->row++;
	} else if (c == '\r') {
		f->col = 0;
	} else {
		unsigned w = 8 * 2, h = 16 * 2;
		if ((f->col + 1) * w > f->w) {
			f->col = 0;
			f->row++;
		}
		unsigned px = f->col * w, py = f->row * h;
		if (py + h > f->h) {
			fb_clear_one(f, 0xff101820u);
			px = 0; py = 0;
		}
		for (unsigned gy = 0; gy < 16; gy++) {
			for (unsigned sy = 0; sy < 2; sy++) {
				volatile uint32_t *line = (volatile uint32_t *)
				    (f->base + (uintptr_t)(py + gy * 2 + sy) * f->stride * 4 + px * 4);
				for (unsigned gx = 0; gx < 8; gx++) {
					uint32_t pxv = (g[gy] & (0x80u >> gx)) ? 0xffffffffu : 0xff101820u;
					for (unsigned sx = 0; sx < 2; sx++)
						line[gx * 2 + sx] = pxv;
				}
			}
		}
		f->col++;
	}
	if ((f->row + 1) * 16 * 2 >= f->h)
		fb_clear_one(f, 0xff101820u);
}

static void fb_glyph(char c)
{
	for (int i = 0; i < nfb; i++)
		fb_glyph_one(&fbs[i], c);
}

/* ---- combined console ------------------------------------------------- */

static void con_putc(char c)
{
	uart_putc(c);
	fb_glyph(c);
}

void con_puts(const char *s)
{
	while (*s)
		con_putc(*s++);
}

static void con_hex_raw(uint64_t v)
{
	con_puts("0x");
	for (int i = 15; i >= 0; i--) {
		unsigned d = (v >> (i * 4)) & 0xf;
		con_putc(d < 10 ? '0' + d : 'a' + d - 10);
	}
}

static void con_dec_raw(uint64_t v)
{
	char buf[24];
	int n = 0;
	if (!v) { con_putc('0'); return; }
	while (v && n < (int)sizeof(buf)) { buf[n++] = '0' + (v % 10); v /= 10; }
	while (n) con_putc(buf[--n]);
}

void con_hex(const char *label, uint64_t v)
{
	con_puts(label);
	con_hex_raw(v);
	con_puts("\n");
}

void con_dec(const char *label, uint64_t v)
{
	con_puts(label);
	con_dec_raw(v);
	con_puts("\n");
}

void con_printf(const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	for (; *fmt; fmt++) {
		if (*fmt != '%') {
			con_putc(*fmt);
			continue;
		}
		fmt++;
		switch (*fmt) {
		case 's': {
			const char *s = va_arg(ap, const char *);
			while (s && *s)
				con_putc(*s++);
			break;
		}
		case 'x':
			con_hex_raw(va_arg(ap, uint64_t));
			break;
		case 'd': {
			int64_t v = va_arg(ap, int64_t);
			if (v < 0) { con_putc('-'); con_dec_raw((uint64_t)(-v)); }
			else con_dec_raw((uint64_t)v);
			break;
		}
		case 'u':
			con_dec_raw(va_arg(ap, uint64_t));
			break;
		case 'c':
			con_putc((char)va_arg(ap, int));
			break;
		case '%':
			con_putc('%');
			break;
		default:
			con_putc('%');
			if (*fmt)
				con_putc(*fmt);
			break;
		}
	}
	va_end(ap);
}
