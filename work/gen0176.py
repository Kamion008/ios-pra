#!/usr/bin/env python3
"""gen0176.py - build xnu/patches/0176-pra-emmc-lock-scope-and-telemetry.patch.

Bases: the CI-compiled tree from run 44119547672 (/tmp/bt441-src/xnu) - the
true series base for 0175-era sources (audit: work/audit-pra-emmc-lock-
2026-11-17.md). Design constraints from claim review round 2:
- per-ITERATION lock/unlock in strat (the :2500-2502 error break must never
  exit holding the lock),
- COUNT/TICK-based limiters (the :1408 timebase constant is unverified),
- the strat tail flush writes NO header (header/total invariant),
- telemetry prints INSIDE the locked region (console + RAM ring are the
  guaranteed channels).
"""
import difflib, os, re, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = "/tmp/bt441-src/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0176-pra-emmc-lock-scope-and-telemetry.patch"

SD = f"{BASE}/bsd/dev/pra_sdhci.c"
EX = f"{BASE}/osfmk/kern/exception.c"
# NOTE: .github/workflows/xnu.yml is NOT patchable - CI applies patches in
# the dxb build tree which has no .github; a yml hunk makes the whole patch
# skip silently there (run 44141348138 built the old asserts and stayed
# green). Workflow assert changes are DIRECT COMMITS to the repo's yml,
# made in the same commit as the patch.

def read(path):
    return open(path, encoding="utf-8").read().splitlines()

def anchor_unique(lines, anchor, tag):
    n = sum(1 for i in range(len(lines))
            if tuple(lines[i:i+len(anchor)]) == tuple(anchor))
    assert n == 1, f"{tag}: anchor not unique ({n} hits): {anchor[0][:60]!r}"
    return next(i for i in range(len(lines))
                if tuple(lines[i:i+len(anchor)]) == tuple(anchor))

def replace_block(lines, anchor, new, tag):
    i = anchor_unique(lines, anchor, tag)
    return lines[:i] + new + lines[i+len(anchor):], f"{tag}: replaced @ line {i+1}"

def insert_before(lines, anchor, new, tag):
    i = anchor_unique(lines, anchor, tag)
    return lines[:i] + new + lines[i:], f"{tag}: inserted before line {i+1}"

# CI-bisect support: NO_LOCKSWAP=1 withholds the tail-flush refactor ([5*],
# [6]) and the per-iteration lock swap ([7], [8], [8b]) - the telemetry
# groups ([2], [3], [4*], [9*]) and the clock stay in.
NO_LOCKSWAP = os.environ.get("NO_LOCKSWAP") == "1"
_real_rb, _real_ib = replace_block, insert_before
def replace_block(lines, anchor, new, tag):  # noqa: F811
    if NO_LOCKSWAP and tag.startswith(("[5", "[6", "[7", "[8")):
        return lines, f"{tag}: SKIPPED (NO_LOCKSWAP bisect)"
    return _real_rb(lines, anchor, new, tag)
def insert_before(lines, anchor, new, tag):  # noqa: F811
    if NO_LOCKSWAP and tag.startswith(("[5", "[6", "[7", "[8")):
        return lines, f"{tag}: SKIPPED (NO_LOCKSWAP bisect)"
    return _real_ib(lines, anchor, new, tag)

def insert_after(lines, anchor, new, tag):
    i = anchor_unique(lines, anchor, tag)
    return lines[:i+1] + new + lines[i+1:], f"{tag}: inserted after line {i+1}"

# ---------------- pra_sdhci.c ----------------
sd = read(SD)
log = []

# sanity: the lock implementation fields we rely on exist in lock_mtx.h
lmh = read(f"{BASE}/osfmk/kern/lock_mtx.h")
assert any("uint32_t                data;" in l for l in lmh), "lock data field"
assert any("lck_mtx_tsid" in l for l in lmh), "tsid field"
assert any("LCK_MTX_ILOCK" in l for l in lmh), "ilock mask"
log.append(f"lock_mtx.h fields verified ({len(lmh)} lines)")

# [1] NO new include: the state word is read through the documented opaque
# view (pra_sdhci.c:1449-1451 "opaque[1] is the state in either layout"),
# the same technique the panic path's zeroing uses - zero typedef risk.

# [2] counters ABOVE pra_log_write_sector - they are used there (:1091) and
# in the flusher's complaint (:1281); the previous anchor (next to the other
# pra_log statics, :1438) put the declarations AFTER the uses -> 4x "use of
# undeclared identifier" + make[7]: *** [pra_sdhci.o] Error 1 (run #66,
# quoted lines 19134-19191 of its job log).
sd, m = insert_before(sd,
    ["static int",
     "pra_log_write_sector(uint32_t lba, const uint8_t *sector)"],
    ["/* 0176: flusher EBUSY attribution (the audit's conflation killer) and",
     " * the request counter for the count-limited tail flush. The owner",
     " * decoder gets a local explicit extern - pra_sdhci.c does not include",
     " * kern/thread.h (thread_t arrives via the :305 extern pattern), so an",
     " * implicit declaration would be fatal under the build's strict flags",
     " * (quoted: pra_sdhci.c:1091/1096/1281 use of undeclared identifier",
     " * 'pra_log_lock_busy'/'pra_log_card_busy', run #66 job log). */",
     "extern thread_t ctid_get_thread_unsafe(uint32_t ctid);",
     "static uint64_t pra_log_lock_busy;",
     "static uint64_t pra_log_card_busy;",
     "static uint64_t pra_emmc_req_count;",
     "",
     ""], "[2] counters above write_sector")
log.append(m)

# [3] pra_log_write_sector: lock-busy vs card-busy attribution
sd, m = replace_block(sd, [
    "\tif (!lck_mtx_try_lock(&pra_emmc_lock)) {",
    "\t\treturn EBUSY;",
    "\t}",
    "\terror = pra_emmc_write_raw(lba, sector);",
    "\tlck_mtx_unlock(&pra_emmc_lock);",
    "\treturn error;",
], [
    "\tif (!lck_mtx_try_lock(&pra_emmc_lock)) {",
    "\t\t/* 0176: the lock was busy - counted separately from card-side",
    "\t\t * failures so the starvation windows become attributable (audit:",
    "\t\t * the old EBUSY conflated the two). */",
    "\t\tpra_log_lock_busy++;",
    "\t\treturn EWOULDBLOCK;",
    "\t}",
    "\terror = pra_emmc_write_raw(lba, sector);",
    "\tif (error) {",
    "\t\tpra_log_card_busy++;",
    "\t}",
    "\tlck_mtx_unlock(&pra_emmc_lock);",
    "\treturn error;",
], "[3] write_sector attribution")
log.append(m)

# [4] the flusher's complaint line + the state dump at 6 consecutive fails
sd, m = insert_before(sd, [
    "\t\t\t\tif (++write_fails <= 8 || write_fails % 64 == 0) {",
    "\t\t\t\t\tprintf(\"PRA LOG: write failed %d after %d ticks\\n\",",
    "\t\t\t\t\t    error, write_fails);",
    "\t\t\t\t}",
], [
    "\t\t\t\tif (write_fails == 5) {",
    "\t\t\t\t\t/* 0176: the wedge discriminator, printed while the lock",
    "\t\t\t\t\t * regime is live (audit fork-(a) vs fork-(b)). Read through",
    "\t\t\t\t\t * the documented opaque view (see the panic path):",
    "\t\t\t\t\t * opaque[1] low-32 = the state word (owner ctid + flags,",
    "\t\t\t\t\t * NEEDS_WAKEUP = 0x40000000 per lock_mtx.h), opaque[0]",
    "\t\t\t\t\t * low-24 = the turnstile id. NEEDS_WAKEUP set with the",
    "\t\t\t\t\t * owner gone and parks out there = waiters nobody wakes;",
    "\t\t\t\t\t * owner ctid held across many ticks = the holder. */",
    "\t\t\t\t\tuint32_t mdata = (uint32_t)(((volatile uintptr_t *)",
    "\t\t\t\t\t    (void *)&pra_emmc_lock)[1]);",
    "\t\t\t\t\tuint32_t mtsid = (uint32_t)(((volatile uintptr_t *)",
    "\t\t\t\t\t    (void *)&pra_emmc_lock)[0]) & 0xffffffu;",
    "\t\t\t\t\tthread_t mo = ctid_get_thread_unsafe(",
    "\t\t\t\t\t    mdata & ~0xf0000000u);",
    "\t\t\t\t\tprintf(\"PRA LOG: lock state data=%08x wakeup=%u \"",
    "\t\t\t\t\t    \"tsid=%u owner=%p\\n\",",
    "\t\t\t\t\t    mdata,",
    "\t\t\t\t\t    (uint32_t)!!(mdata & 0x40000000u),",
    "\t\t\t\t\t    mtsid,",
    "\t\t\t\t\t    mo);",
    "\t\t\t\t}",
], "[4a] state dump")
log.append(m)
sd, m = replace_block(sd, [
    "\t\t\t\tif (++write_fails <= 8 || write_fails % 64 == 0) {",
    "\t\t\t\t\tprintf(\"PRA LOG: write failed %d after %d ticks\\n\",",
    "\t\t\t\t\t    error, write_fails);",
    "\t\t\t\t}",
], [
    "\t\t\t\tif (++write_fails <= 8 || write_fails % 64 == 0) {",
    "\t\t\t\t\tprintf(\"PRA LOG: write failed %d after %d ticks \"",
    "\t\t\t\t\t    \"(lock=%llu card=%llu)\\n\",",
    "\t\t\t\t\t    error, write_fails,",
    "\t\t\t\t\t    pra_log_lock_busy, pra_log_card_busy);",
    "\t\t\t\t}",
], "[4b] complaint line")
log.append(m)

# [5] the tail-only flush helper + flush_locked refactored onto it
sd, m = insert_before(sd, [
    "static int",
    "pra_log_flush_locked(uint64_t start, uint64_t blocks, uint64_t total,",
    "    uint32_t seq)",
], [
    "/* 0176: the block-copy loop WITHOUT the header write. The header's",
    " * total must keep meaning \"the periodic flusher fully flushed 0..total\"",
    " * - the ring accounting (and every pull comparison) relies on it - so",
    " * partial flushes (strat's tail) must not touch it. The panic path",
    " * keeps the full rewrite + header via pra_log_flush_locked. */",
    "static int",
    "pra_log_flush_tail_locked(uint64_t start, uint64_t blocks)",
    "{",
    "\tuint8_t sector[512];",
    "\tint error = 0;",
    "",
    "\tif (start >= PRA_LOG_SIZE / 512u) {",
    "\t\treturn EINVAL;",
    "\t}",
    "\tif (start + blocks > PRA_LOG_SIZE / 512u) {",
    "\t\tblocks = PRA_LOG_SIZE / 512u - start;",
    "\t}",
    "\tfor (uint64_t block = start; block < start + blocks && !error;",
    "\t    block++) {",
    "\t\tmemcpy(sector, pra_log_ring + (size_t)block * 512u,",
    "\t\t    sizeof(sector));",
    "\t\terror = pra_emmc_write_raw((uint32_t)(pra_log_erecovery_lba + 1u +",
    "\t\t    block), sector);",
    "\t}",
    "\treturn error;",
    "}",
    "",
], "[5a] tail helper")
log.append(m)
sd, m = replace_block(sd, [
    "\tfor (uint64_t block = start; block < start + blocks && !error;",
    "\t    block++) {",
    "\t\tmemcpy(sector, pra_log_ring + (size_t)block * 512u,",
    "\t\t    sizeof(sector));",
    "\t\terror = pra_emmc_write_raw((uint32_t)(pra_log_erecovery_lba + 1u +",
    "\t\t    block), sector);",
    "\t}",
    "\tif (!error) {",
    "\t\tstruct pra_log_header h = {",
    "\t\t\t.magic = { 'P', 'R', 'A', 'L', 'O', 'G', '1', '\\0' },",
    "\t\t\t.version = 1,",
    "\t\t\t.size = PRA_LOG_SIZE,",
    "\t\t\t.total = total,",
    "\t\t\t.seq = seq,",
    "\t\t};",
    "\t\tmemset(sector, 0, sizeof(sector));",
    "\t\tmemcpy(sector, &h, sizeof(h));",
    "\t\terror = pra_emmc_write_raw((uint32_t)pra_log_erecovery_lba, sector);",
    "\t}",
    "\treturn error;",
], [
    "\terror = pra_log_flush_tail_locked(start, blocks);",
    "\tif (!error) {",
    "\t\tstruct pra_log_header h = {",
    "\t\t\t.magic = { 'P', 'R', 'A', 'L', 'O', 'G', '1', '\\0' },",
    "\t\t\t.version = 1,",
    "\t\t\t.size = PRA_LOG_SIZE,",
    "\t\t\t.total = total,",
    "\t\t\t.seq = seq,",
    "\t\t};",
    "\t\tmemset(sector, 0, sizeof(sector));",
    "\t\tmemcpy(sector, &h, sizeof(h));",
    "\t\terror = pra_emmc_write_raw((uint32_t)pra_log_erecovery_lba, sector);",
    "\t}",
    "\treturn error;",
], "[5b] flush_locked onto the tail helper")
log.append(m)

# [6] strat's evidence flush: tail-only now (the header invariant)
sd, m = replace_block(sd, [
    "\terror = pra_log_flush_locked(start, blocks, total,",
    "\t    (uint32_t)pra_log_seq);",
], [
    "\t/* 0176: tail-only, header-less - see pra_log_flush_tail_locked. */",
    "\terror = pra_log_flush_tail_locked(start, blocks);",
], "[6] strat flush tail-only")
log.append(m)

# [7] strat: per-iteration locking (swap 1)
sd, m = replace_block(sd, [
    "\tlck_mtx_lock(&pra_emmc_lock);",
    "\tfor (uint32_t n = 0; n < count;) {",
], [
    "\t/* 0176: the lock is per sector/chunk now. A whole-request hold on a",
    "\t * slow card parked every strat caller on this mutex for minutes -",
    "\t * hours (the wedge) while the periodic flusher starved (rings 34-39).",
    "\t * The error break below stays OUTSIDE the locked section. */",
    "\tfor (uint32_t n = 0; n < count;) {",
    "\t\tlck_mtx_lock(&pra_emmc_lock);",
], "[7] lock per iteration (swap 1)")
log.append(m)

# [8] strat: count-limited tail flush inside the locked section, then
# unlock BEFORE the error check (swap 2)
sd, m = replace_block(sd, [
    "\t\tif (error) {",
    "\t\t\tbreak;",
    "\t\t}",
    "\t\tn += take;",
    "\t\tbuf_setresid(bp, count - n);",
    "\t}",
    "\tlck_mtx_unlock(&pra_emmc_lock);",
], [
    "\t\tif (++pra_emmc_req_count % 128u == 0u) {",
    "\t\t\t/* 0176: tail flush from inside the locked section (the",
    "\t\t\t * documented strat_flush contract), count-limited, header-less. */",
    "\t\t\tpra_log_strat_flush(true);",
    "\t\t}",
    "\t\tlck_mtx_unlock(&pra_emmc_lock);",
    "\t\tif (error) {",
    "\t\t\tbreak;",
    "\t\t}",
    "\t\tn += take;",
    "\t\tbuf_setresid(bp, count - n);",
    "\t}",
], "[8] unlock per iteration (swap 2)")
log.append(m)

# [8b] the successful-chunk path ends in `continue`, which in the per-
# iteration structure would skip the bottom unlock - release the mutex
# right there (CI bisect: run 44165122932 failed; runtime self-deadlock).
# Anchor extended with the rung block: the base has THREE 4-tab continues
# (:1660, :1666, :2445).
sd, m = insert_before(sd, [
    "\t\t\t\t\t    pra_emmc_multi_rung]);",
    "\t\t\t\t}",
    "\t\t\t\tcontinue;",
], [
    "\t\t\t\t\t    pra_emmc_multi_rung]);",
    "\t\t\t\t}",
    "\t\t\t\t/* 0176: this chunk path skips the per-sector tail of the",
    "\t\t\t\t * loop, so it must release the mutex the per-iteration",
    "\t\t\t\t * structure acquires at the top. */",
    "\t\t\t\tlck_mtx_unlock(&pra_emmc_lock);",
    "\t\t\t\tcontinue;",
], "[8b] unlock before the chunk continue")
log.append(m)

# [9] the large-request line, once per request, after the loop
sd, m = insert_before(sd, ["\tbuf_unmap(bp);"], [
    "\tif (pra_log_lock_busy > pra_emmc_lock_busy_mark && count >= 64u * 512u) {",
    "\t\t/* 0176: name the big requests while the flusher is starving -",
    "\t\t * the contention-unit evidence (audit C1). */",
    "\t\tprintf(\"PRA eMMC: %u-sector request lba=%u is_read=%d while \"",
    "\t\t    \"flusher lockbusy=%llu card=%llu\\n\",",
    "\t\t    (uint32_t)(count >> 9),",
    "\t\t    (uint32_t)(pra_emmc_first_lba + off / 512u), is_read,",
    "\t\t    pra_log_lock_busy, pra_log_card_busy);",
    "\t\tpra_emmc_lock_busy_mark = pra_log_lock_busy + 16;",
    "\t}",
], "[9] large-request line")
log.append(m)

# [9b] the mark static
sd, m = insert_before(sd, [
    "/* 0176: flusher EBUSY attribution (the audit's conflation killer) and",
], ["static uint64_t pra_emmc_lock_busy_mark;"], "[9b] mark static")
log.append(m)

# ---------------- exception.c ----------------
NO_CLOCK = os.environ.get("NO_CLOCK") == "1"
if NO_CLOCK:
    log.append("NO_CLOCK=1: exception.c hunks withheld (CI bisect)")
    ex = None
else:
    ex = read(EX)

if not NO_CLOCK:
    # [10] the calendar clock in the sampler header (H2 discriminator)
    ex, m = replace_block(ex, [
        "\tprintf(\"SMP %s[%d] slide 0x%llx mh 0x%llx\\n\", name, pid, slide, task->mach_header_vm_address);",
    ], [
        "\t/* 0176: the wall clock next to the per-process header - the H2",
        " * never-redrawn-vs-frozen discriminator (boots #4/#5 rendered 4:07 vs",
        " * boots #1-#3/#6 at 4:08; no in-boot advance). Also measures the real",
        " * timebase scale against the calendar. clock_sec_t/clock_usec_t are",
        " * the prototype's own types (clock.h:51-57 - usec is 32-bit). */",
        "\tclock_sec_t cal_s = 0;",
        "\tclock_usec_t cal_us = 0;",
        "\tclock_get_calendar_microtime(&cal_s, &cal_us);",
        "\tprintf(\"SMP %s[%d] slide 0x%llx mh 0x%llx cal=%llu.%06llu\\n\",",
        "\t    name, pid, slide, task->mach_header_vm_address,",
        "\t    (uint64_t)cal_s, (uint64_t)cal_us);",
    ], "[10] sampler clock")
    log.append(m)

    # [11] clock.h include (idempotent: skip if already present)
    if not any("kern/clock.h" in l for l in ex):
        inc2 = next(i for i, l in enumerate(ex) if l.startswith("#include <kern/"))
        ex, m = insert_before(ex, [ex[inc2]],
                              ["#include <kern/clock.h>"], "[11] clock include")
        log.append(m)
    else:
        log.append("[11] clock.h already included - skipped")

# ---------------- xnu.yml ----------------
# [12] marker asserts: these go into the REPO's yml via the orchestrator's
# direct edit (same commit as the patch), NOT via this patch - see the
# header note above. The generator does not touch the yml at all.

# ---------------- emit the patch ----------------
d1 = difflib.unified_diff(read(SD), sd, fromfile="a/bsd/dev/pra_sdhci.c",
                          tofile="b/bsd/dev/pra_sdhci.c", n=3, lineterm="")
if NO_CLOCK:
    d2 = ()
else:
    d2 = difflib.unified_diff(read(EX), ex, fromfile="a/osfmk/kern/exception.c",
                              tofile="b/osfmk/kern/exception.c", n=3, lineterm="")

header = """pra: 0176 - per-sector eMMC locking + wedge discriminator telemetry

Audit (work/audit-pra-emmc-lock-2026-11-17.md): strat held pra_emmc_lock
across its whole request loop; on a slow/stuck card one large request held
the mutex for minutes-to-hours while launchd sync/backboardd parked on it
UNINT (the wedge) and the periodic flusher starved (healthy boots: 0-9 of
~90 successful flush ticks; the wedged boot's terminal park state was never
flushed - self-erasing evidence). Claim review: pkt-175415 (round 1: 3
refuted / 3 weak / 1 survive -> revisions), pkt-182616 (round 2: 1 refuted /
10 weak / 5 survive -> revisions); patch review pkt-184450 (0 refuted /
7 weak / 3 survive -> wording + type fixes adopted).

- strat: the lock is per sector/chunk now (per-iteration lock/unlock; the
  error break stays OUTSIDE the locked section - review C5-1). A slow card
  degrades to slow IO; the flusher and parked waiters interleave.
- The flusher's complaint line separates lock-EBUSY from card-side errors
  (pra_log_write_sector returns EWOULDBLOCK on try_lock failure and counts
  both paths), and at 6 consecutive failures prints the mutex state
  (data word + turnstile id + decoded owner) while the lock regime is
  live - the fork-(a) stuck-holder vs (b) lost-wakeup discriminator.
- Large requests name themselves while the flusher is starving.
- strat flushes the ring tail (count-limited, every 128 requests) from
  inside its locked section; the tail flush writes NO header so the
  "header total = fully-flushed boundary" invariant stays intact (the
  panic path keeps the full rewrite + header).
- The sampler header line carries clock_get_calendar_microtime (the H2
  never-redrawn-vs-frozen discriminator; also measures the real timebase
  scale, settling the 1.92-vs-19.2 MHz limiter question).

Markers asserted in CI: 'PRA LOG: lock state data=',
'(lock=%llu card=%llu)', 'cal=%llu.%06llu'.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header + "\n".join(list(d1) + list(d2)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0176")
verify_pairs = [("bsd/dev/pra_sdhci.c", read(SD), sd)]
if not NO_CLOCK:
    verify_pairs.append(("osfmk/kern/exception.c", read(EX), ex))
for path, base, content in verify_pairs:
    fp = os.path.join(scratch, path)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    open(fp, "w").write("\n".join(base) + "\n")
subprocess.run(["git", "init", "-q", scratch], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.email", "v@v"], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.name", "v"], check=True)
subprocess.run(["git", "-C", scratch, "add", "-A"], check=True)
subprocess.run(["git", "-C", scratch, "commit", "-qm", "base"], check=True)
r0 = subprocess.run(["git", "-C", scratch, "apply", "--check", "-v", OUT],
                    capture_output=True, text=True)
print(f"[verify] git apply --check rc={r0.returncode}")
for l in (r0.stdout + r0.stderr).splitlines():
    if any(k in l for k in ("Skipped", "error", "Checking")):
        print("    " + l)
assert r0.returncode == 0 and "Skipped" not in (r0.stdout + r0.stderr)
r2 = subprocess.run(["patch", "-p1", "--fuzz=0", "--dry-run", "-i", OUT],
                    cwd=scratch, capture_output=True, text=True)
print(f"[verify] GNU patch --fuzz=0 --dry-run rc={r2.returncode}")
assert r2.returncode == 0, r2.stdout + r2.stderr
r = subprocess.run(["git", "-C", scratch, "apply", "-v", OUT],
                   capture_output=True, text=True)
print(f"[verify] git apply rc={r.returncode}")
assert r.returncode == 0 and "Skipped" not in (r.stdout + r.stderr)
# use-before-declaration guard (run #66: the counters were declared at :1438
# while write_sector used them from :1091 - 4x "use of undeclared identifier"
# + make[7]: *** [pra_sdhci.o] Error 1; the diff-only verify cannot catch it)
for sym in ("pra_log_lock_busy", "pra_log_card_busy", "pra_emmc_req_count",
            "pra_emmc_lock_busy_mark"):
    decl = next(i for i, l in enumerate(sd) if f"static uint64_t {sym};" in l)
    first_use = next(i for i, l in enumerate(sd)
                     if sym in l and i != decl
                     and not l.lstrip().startswith(("//", "/*", "*")))
    assert first_use > decl, \
        f"{sym}: use at {first_use+1} [{sd[first_use][1:60]}] precedes decl at {decl+1} [{sd[decl][1:60]}]"
    print(f"[verify] {sym}: decl {decl+1} < first use {first_use+1}")
for path, base, expect in verify_pairs:
    got = open(os.path.join(scratch, path)).read()
    assert got == "\n".join(expect) + "\n", f"{path} mismatch"
    print(f"[verify] {path}: applied == expected")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0176 applies to the CI-compiled bases")
