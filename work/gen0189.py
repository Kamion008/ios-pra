#!/usr/bin/env python3
"""gen0189.py - build xnu/patches/0189-pra-touch-length-poll.patch.

Base: work/ci189/pre0189/xnu = work/ci188/pre0188/xnu (the post-0187
reconstruction) + the 0188 patch applied; 0188 and 0189 touch
bsd/dev/pra_touch.c only.

BOOT T12 (ring53) + the vendor sources (work/rvr/cyttsp5/):
the 0188 level wait reads gpio28.0 LOW before power and the pad never
changes (T12: irq lo/hi 1000/0, then 2000/0), so "LOW = asserted"
fires instantly - the pure read lands before the IC has prepared the
response. T12's 32-byte read started 00 00 = the vendor's zero-length
"nothing pending" response word (cyttsp5_i2c.c:175+ read_default_nosize:
size = LE16(buf), 0 or 2 = nothing pending, else a pure read of `size`
bytes, the length word repeated at the payload start). The rest of the
32 bytes was stale buffer; len=0 bcd=0x76d2, the parse failed.

The 0188 attempt line also printed a pointer's low word (118017742)
instead of the attempt number: the patch emitted
    printf("PRA touch: desc attempt %d: the response ",
        "received (%u bytes), ...", attempt + 1, ...);
i.e. the second string became a printf ARGUMENT, so %d consumed the
pointer and the wait levels never printed. 0189 fixes the argument
list and prints hdr/irq on every outcome.

THIS PATCH (0189):
1. After the request, poll the 2-byte response length word (pure
   read, 5 ms ticks, 200 ms - the vendor's descriptor timeout class)
   instead of trusting the pad level: 0 or 2 = nothing pending,
   retry; any other value = the response is ready.
2. Read exactly `hlen` bytes (hl=en <= HID_DESC_SIZE; oversize is
   refused), zero-filling the rest of the 32-byte descriptor buffer.
3. The attempt line prints irq start->end, wait outcome, and hdr;
   the 0188 argument bug is gone.
4. The parse-failure trail prints all 32 raw bytes.

Marker asserted in CI (direct yml commit): 'no response after'.
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = f"{REPO}/work/ci189/pre0189/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0189-pra-touch-length-poll.patch"
TARGET = "bsd/dev/pra_touch.c"


def read(path):
    return open(path, encoding="utf-8").read().splitlines()


def find_one(lines, pred, tag):
    hits = [i for i, l in enumerate(lines) if pred(l)]
    assert len(hits) == 1, f"{tag}: {len(hits)} hits"
    return hits[0]


NEW_FN = [
    "/* 0189: the RESPONSE-LENGTH poll (boot T12, ring53). The 0188",
    " * level wait samples the pad LOW before power and it never changes",
    " * (T12: irq lo/hi 1000/0, 2000/0), so \"LOW = asserted\" fires",
    " * instantly and the pure read lands before the IC has prepared the",
    " * response: T12's 32 bytes started 00 00 = the vendor's zero-length",
    " * \"nothing pending\" word, and the rest was stale buffer. The",
    " * vendor never reads on a timer: its IRQ handler runs",
    " * cyttsp5_i2c.c:175+ read_default_nosize = a PURE 2-byte read,",
    " * size = LE16, 0 or 2 = nothing pending, else a pure read of",
    " * `size` bytes (the length word repeats at the payload start). The",
    " * pad is unusable, so poll the length word itself: 5 ms ticks to",
    " * 200 ms (the descriptor timeout class), then read `size` bytes.",
    " * The level wait stays as the fast path and its levels still print.",
    " * Issued TWICE (the BL_LAUNCH reset window - cyttsp5_core.c:2864-",
    " * 2867). */",
    "static int",
    "pra_touch_desc_read(uint8_t *desc)",
    "{",
    "\tuint8_t req[2] = { 0x01u, 0x00u };",
    "\tuint8_t lenb[2];",
    "\tint error = 0;",
    "\tint attempt;",
    "",
    "\tfor (attempt = 0; attempt < 2; attempt++) {",
    "\t\tunsigned irq_start = 0, irq_end = 0;",
    "\t\tunsigned waited_ms = 0;",
    "\t\tuint32_t hlen = 0;",
    "\t\tint waited = 0, wait_error = 0;",
    "",
    "\t\tprintf(\"PRA touch: desc attempt %d: request...\\n\",",
    "\t\t    attempt + 1);",
    "\t\terror = pra_touch_txn(req, 2, NULL, 0);",
    "\t\tif (error == 0) {",
    "\t\t\twaited = 1;",
    "\t\t\twait_error = pra_touch_desc_wait_int(&irq_start,",
    "\t\t\t    &irq_end);",
    "\t\t\tfor (waited_ms = 0; waited_ms < 200u;",
    "\t\t\t    waited_ms += 5u) {",
    "\t\t\t\terror = pra_touch_txn(NULL, 0, lenb, 2);",
    "\t\t\t\tif (error) {",
    "\t\t\t\t\tbreak;",
    "\t\t\t\t}",
    "\t\t\t\thlen = pra_touch_le16(lenb);",
    "\t\t\t\tif (hlen != 0 && hlen != 2) {",
    "\t\t\t\t\tbreak;",
    "\t\t\t\t}",
    "\t\t\t\t(void)tsleep(&pra_touch_chan, PZERO,",
    "\t\t\t\t    \"pradescl\", pra_touch_ms_ticks(5u));",
    "\t\t\t}",
    "\t\t\tif (error == 0 && hlen != 0 && hlen != 2 &&",
    "\t\t\t    hlen > HID_DESC_SIZE) {",
    "\t\t\t\tprintf(\"PRA touch: desc attempt %d: \"",
    "\t\t\t\t    \"oversize response hdr=%#x\\n\",",
    "\t\t\t\t    attempt + 1, hlen);",
    "\t\t\t\terror = EIO;",
    "\t\t\t}",
    "\t\t}",
    "\t\tif (error == 0 && hlen != 0 && hlen != 2) {",
    "\t\t\tmemset(desc, 0, HID_DESC_SIZE);",
    "\t\t\terror = pra_touch_txn(NULL, 0, desc, hlen);",
    "\t\t}",
    "\t\tif (error == 0 && hlen != 0 && hlen != 2) {",
    "\t\t\tprintf(\"PRA touch: desc attempt %d: the response \"",
    "\t\t\t    \"received (%u bytes, hdr=%#x), irq %u->%u%s\\n\",",
    "\t\t\t    attempt + 1, hlen, hlen, irq_start, irq_end,",
    "\t\t\t    wait_error ? \", the wait timed out\" : \"\");",
    "\t\t\treturn 0;",
    "\t\t}",
    "\t\tif (error == 0) {",
    "\t\t\tprintf(\"PRA touch: desc attempt %d: no response \"",
    "\t\t\t    \"after %u ms (hdr=%#x), irq %u->%u%s\\n\",",
    "\t\t\t    attempt + 1, waited_ms, hlen, irq_start, irq_end,",
    "\t\t\t    wait_error ? \", the wait timed out\" : \"\");",
    "\t\t\terror = ETIMEDOUT;",
    "\t\t} else if (waited) {",
    "\t\t\tprintf(\"PRA touch: desc attempt %d failed err=%d \"",
    "\t\t\t    \"(irq %u->%u, wait=%s, hdr=%#x)\\n\", attempt + 1,",
    "\t\t\t    error, irq_start, irq_end,",
    "\t\t\t    wait_error ? \"timeout\" : \"asserted\", hlen);",
    "\t\t} else {",
    "\t\t\tprintf(\"PRA touch: desc attempt %d failed err=%d \"",
    "\t\t\t    \"(the request)\\n\", attempt + 1, error);",
    "\t\t}",
    "\t}",
    "\treturn error;",
    "}",
]

NEW_RAW = [
    "\t\t\t/* 0189: the framing trail - all 32 bytes print on",
    "\t\t\t * EVERY failed parse (not only under pratouchdbg):",
    "\t\t\t * the first word is the vendor's response length",
    "\t\t\t * (0x20 = the descriptor is ready); 0000 = nothing",
    "\t\t\t * pending (the read raced the response). */",
    "\t\t\tprintf(\"PRA touch: desc raw=%02x %02x %02x %02x \"",
    "\t\t\t    \"%02x %02x %02x %02x %02x %02x %02x %02x \"",
    "\t\t\t    \"%02x %02x %02x %02x %02x %02x %02x %02x \"",
    "\t\t\t    \"%02x %02x %02x %02x %02x %02x %02x %02x \"",
    "\t\t\t    \"%02x %02x %02x %02x\\n\",",
    "\t\t\t    desc[0], desc[1], desc[2], desc[3],",
    "\t\t\t    desc[4], desc[5], desc[6], desc[7],",
    "\t\t\t    desc[8], desc[9], desc[10], desc[11],",
    "\t\t\t    desc[12], desc[13], desc[14], desc[15],",
    "\t\t\t    desc[16], desc[17], desc[18], desc[19],",
    "\t\t\t    desc[20], desc[21], desc[22], desc[23],",
    "\t\t\t    desc[24], desc[25], desc[26], desc[27],",
    "\t\t\t    desc[28], desc[29], desc[30], desc[31]);",
]

pt = read(f"{BASE}/{TARGET}")
log = []

# [1] replace the 0188 comment + whole pra_touch_desc_read function
i0 = find_one(pt, lambda l: l.startswith(
    "/* 0188: the ASYNCHRONOUS descriptor read"), "[1] the 0188 fn comment")
i_fn = find_one(pt, lambda l: l.startswith(
    "pra_touch_desc_read(uint8_t *desc)"), "[1] the fn signature")
i_open = next(i for i in range(i_fn, len(pt)) if pt[i].strip() == "{")
depth = 0
i_close = None
for j in range(i_open, len(pt)):
    depth += pt[j].count("{") - pt[j].count("}")
    if depth == 0:
        i_close = j
        break
assert i_close is not None, "[1] no closing brace"
pt = pt[:i0] + NEW_FN + pt[i_close + 1:]
log.append(f"[1] desc_read replaced: lines {i0 + 1}..{i_close + 1}")

# [2] the raw trail: 16 -> 32 bytes
i_c = find_one(pt, lambda l: "0188: the framing trail" in l,
               "[2] the raw comment")
i_end = next(i for i in range(i_c, len(pt)) if "desc[15]);" in pt[i])
pt = pt[:i_c] + NEW_RAW + pt[i_end + 1:]
log.append(f"[2] raw trail 16->32 bytes: lines {i_c + 1}..{i_end + 1}")

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), pt,
                          fromfile="a/bsd/dev/pra_touch.c",
                          tofile="b/bsd/dev/pra_touch.c", n=3, lineterm="")

header = """pra: 0189 - the descriptor RESPONSE-LENGTH poll + the attempt printf fix

Boot T12 (ring53, fresh [512, 252032) = 251,529 B / 5,496 lines) +
the vendor sources (work/rvr/cyttsp5/): the 0188 level wait samples
gpio28.0 LOW before power and the pad never changes (T12: the
worker's irq lo/hi 1000/0, then 2000/0), so "LOW = asserted" fires
instantly - the pure read lands before the IC has prepared the
response. T12's 32-byte read started 00 00 = the vendor's zero-length
"nothing pending" response word (cyttsp5_i2c.c:175+
read_default_nosize: size = LE16, 0 or 2 = nothing pending, else a
pure read of `size` bytes, the length word repeated at the payload
start). The remaining 30 bytes were stale buffer; len=0
bcd=0x76d2, so the parse failed. The read path itself worked: err=0,
32 bytes transferred, and the unconditional-read gate did its job.

The 0188 attempt line also printed a pointer's low word (118017742)
instead of the attempt number: the patch emitted
    printf("PRA touch: desc attempt %d: the response ",
        "received (%u bytes), ...", attempt + 1, ...);
i.e. the second string became a printf ARGUMENT, so %d consumed the
pointer and the wait levels never printed. 0189 fixes the argument
list and prints hdr/irq on every outcome.

This patch (0189):
1. After the request, poll the 2-byte response length word (pure
   read, 5 ms ticks, 200 ms - the vendor's descriptor timeout class)
   instead of trusting the pad level: 0 or 2 = nothing pending,
   retry; any other value = the response is ready.
2. Read exactly `hlen` bytes (hl=en <= HID_DESC_SIZE; oversize is
   refused), zero-filling the rest of the 32-byte descriptor buffer.
3. The attempt line prints irq start->end, the wait outcome, and hdr;
   the 0188 argument bug is gone.
4. The parse-failure trail prints all 32 raw bytes.

Decodes (the next pratouchreset=1 boot): hdr=0x20 + the parse
passes (len=32 bcd=0x100) = app mode confirmed, pra_live=true, the
reports flow; hdr=0x20 + the parse fails = the framing/offset rung
with all 32 bytes in the ring; `no response after 200 ms (hdr=0)` on
both attempts = the IC never prepared a response (the mode/command
rung - the BL_LAUNCH did not take); err=6/60 with a txn error = the
bus rung.

Marker asserted in CI (direct yml commit): 'no response after'.
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header)
    f.write("\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0189")
fp = os.path.join(scratch, TARGET)
os.makedirs(os.path.dirname(fp), exist_ok=True)
open(fp, "w").write("\n".join(read(f"{BASE}/{TARGET}")) + "\n")
subprocess.run(["git", "init", "-q", scratch], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.email", "v@v"], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.name", "v"], check=True)
subprocess.run(["git", "-C", scratch, "add", "-A"], check=True)
subprocess.run(["git", "-C", scratch, "commit", "-qm", "base"], check=True)
r0 = subprocess.run(["git", "-C", scratch, "apply", "--check", "-v", OUT],
                    capture_output=True, text=True)
print(f"[verify] git apply --check rc={r0.returncode}")
assert r0.returncode == 0 and "Skipped" not in (r0.stdout + r0.stderr)
r2 = subprocess.run(["patch", "-p1", "--fuzz=0", "--dry-run", "-i", OUT],
                    cwd=scratch, capture_output=True, text=True)
print(f"[verify] GNU patch --fuzz=0 --dry-run rc={r2.returncode}")
assert r2.returncode == 0, r2.stdout + r2.stderr
r = subprocess.run(["git", "-C", scratch, "apply", "-v", OUT],
                   capture_output=True, text=True)
print(f"[verify] git apply rc={r.returncode}")
assert r.returncode == 0 and "Skipped" not in (r.stdout + r.stderr)
got = open(os.path.join(scratch, TARGET)).read()
assert got == "\n".join(pt) + "\n", "pra_touch.c mismatch"
print("[verify] pra_touch.c: applied == expected")

# structural assertions
scan = "\n".join(pt)
i_wait = scan.index("pra_touch_desc_wait_int(unsigned *start")
i_fn = scan.index("pra_touch_desc_read(uint8_t *desc)")
i_worker = scan.index("kernel_thread_start(pra_touch_thread")
assert i_wait < i_fn < i_worker, "order: wait < desc_read < worker"
print("[verify] order: wait < desc_read < worker")
assert scan.count("pra_touch_txn(NULL, 0, lenb, 2)") == 1, "the length read once"
assert scan.count("pra_touch_txn(NULL, 0, desc, hlen)") == 1, "the payload read once"
assert scan.count("memset(desc, 0, HID_DESC_SIZE)") == 1, "the zero-fill once"
# the two-line format literals concatenate at compile time; check the parts
assert scan.count('%d: no response "') == 1 and scan.count('"after %u ms') == 1, "the no-response line once"
assert scan.count("PRA touch: desc raw=%02x") == 1, "the raw trail once"
assert scan.count('%d: the response "') == 1 and scan.count('"received (%u bytes, hdr=%#x)') == 1, "the fixed success line once"
assert '"received (%u bytes)' not in scan, "the 0188 argument bug is gone"
assert "\"received (%u bytes), irq" not in scan, "the 0188 argument bug is gone (2)"
assert scan.count("#define PRA_TOUCH_IRQ_ASSERTED") == 1, "the level constant once"
# the payload read follows the length poll and the hlen gate
i_poll = scan.index("pra_touch_txn(NULL, 0, lenb, 2)")
i_read = scan.index("pra_touch_txn(NULL, 0, desc, hlen)")
assert i_poll < i_read, "poll before the payload read"
i_gate = scan.index("if (error == 0 && hlen != 0 && hlen != 2)")
assert i_gate < i_read, "the read is behind the hlen gate"
assert scan.count("{") == scan.count("}"), "brace balance"
print("[verify] structural assertions PASS (length poll, hlen gate, raw 32, braces)")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0189 applies to the reconstructed post-0188 base")
