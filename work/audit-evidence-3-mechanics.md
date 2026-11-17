# EVIDENCE 3 — mechanical facts (pra_sdhci.c, patch stack, boot outcomes)

## Every poll loop in the driver is bounded

for-loop iteration bounds (grep "for ("): init loop 4,000,000 max (line 350);
command poll loops 2,000,000 (lines 495, 536, 579, 721, 752, 790, 832, 978,
1006, 1032, 1762, 1781); helper loops 100k-200k (405, 412, 630, 650, 656).
The only unbounded loops are the flusher thread's `for (;;)` (:1200) and
pra_log_halt's wfe loop (:1113) — thread lifetime, not IO waits.

## No interrupt context takes the mutex

- "polled PIO, no DMA, no interrupts" (:7); "buffer-ready is in PIO, no
  interrupts are enabled" (:109).
- _cnputc may run in any context; pra_log_append is lock-free (:1095-1107).
- grep wakeup( and assert_wait in the driver: 0 hits.

## The panic-path steal has exactly one caller

osfmk/kern/debug.c:1464-1467:

 1464	 * ring out synchronously. Best effort; see pra_log_panic_flush().
 1466	extern void pra_log_panic_flush(void);
 1467	pra_log_panic_flush();

debug.c is the panic handler — the opaque[1] zeroing at pra_sdhci.c:1461
runs only during panic.

## The patch stack never modified XNU's lock primitives

`grep -ln "lck_mtx" xnu/patches/*.patch` -> 0014, 0028, 0030, 0047, 0075,
0104, 0110, 0124, 0139, 0140, 0142, 0149, 0152, 0156, 0158, 0159, 0166.
Every one of these modifies only driver/console files (bsd/dev/*,
osfmk/console/serial_console.c, iokit/bsddev/*, bsd/conf/files). No patch
touches osfmk/kern/locks* or any machine locks implementation. The mutex
implementation is stock xnu-8796.141.3.

## strat's flush call sites (all inside the locked request loop)

 2423: pra_log_strat_flush(false);   (emmctest probe-failure branch)
 2468: pra_log_strat_flush(false);   (CMD18 chunk failure)
 2473: pra_log_strat_flush(true);    (2-strike latch)
There is NO strat flush on the per-sector CMD17 path.

## Boot outcomes in the measured window (work/boots.md)

- Pre-series: 2 of 3 boots reached the lock screen; 1 wedged (ring34's boot).
- 2026-11-17 baseline series, frozen 0175 image (kernel sha
  29512a04dba33d8a5281, VERIFIED pre-flight readback):
  boot #1 15:58:14 -> lock screen 8m30s (ring35 pulled 16:29 from TWRP);
  boot #2 16:30:31 -> lock screen (user: "same as boot 1, no changes");
  boot #3 17:03:34 -> lock screen (user: "same as boot 2");
  boot #4 17:27:55 -> outcome pending at packet time.
- The lock-screen clock reads 4:08 in every observed boot (two readings at
  different uptimes in boot #1, both 4:08).
