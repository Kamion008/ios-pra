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
  boot #1 15:58:14 -> lock screen 8m30s, clock 4:08 (ring35 pulled 16:29);
  boot #2 16:30:31 -> lock screen, clock 4:08 (user: "same as boot 1");
  boot #3 17:03:34 -> lock screen, clock 4:08 (user: "same as boot 2");
  boot #4 17:27:55 -> lock screen, clock 4:07 (user: "WORKED ... probably
      booted in less time"; ring38 pulled ~17:45 from TWRP);
  boot #5 17:45:27 -> lock screen, clock 4:07 (user: "AGAIN, 4:07 in lock
      screen"; ring39 pulled ~18:02 from TWRP);
  boot #6 18:02:24 -> in flight at packet-update time.
- Clock pattern: 4:08 x3 (boots #1-3, ~8m30s class) then 4:07 x2 (boots
  #4-5, shorter class per user report). Within boot #1 the label showed
  4:08 at two DIFFERENT uptimes (~10 and ~15 min) — no in-boot advance.
- User corroboration (2026-11-17, chat): the "PRA LOG: write failed 16
  after N ticks" signature "already happened on most boot[s] but it was
  temporary" — i.e. flusher starvation windows are a known, usually
  transient phenomenon; corroborated independently by ring35's short-burst
  failures and by pra_sdhci.c:1084's ring21/ring20 precedent comment.
- Symbol check (nm on the 0175 CI kernel artifact, run 43958048368):
  `fffffff00844dc00 b _pra_emmc_lock` — the park event address
  we=0xfffffff00844dc08 = _pra_emmc_lock + 0x8 EXACTLY. The parked threads
  are parked on the driver's mutex state word (script-verified).
- ctid_get_thread_unsafe: declared `extern thread_t
  ctid_get_thread_unsafe(ctid_t ctid);` at osfmk/kern/thread.h:1643 —
  callable from bsd/dev (the driver already uses kern externs, e.g.
  kernel_thread_start at pra_sdhci.c:305).
