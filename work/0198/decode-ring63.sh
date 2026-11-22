#!/bin/sh
# T21 decode: the greps that read the power-key control out of ring63.
#   PRA_SERIAL=... sh work/0198/decode-ring63.sh
# Run from the repo root, phone in TWRP. Never boots anything.
set -eu
TXT=${TXT:-work/ring63-full.txt}
RAW=${RAW:-work/ring63.raw}

[ -f "$TXT" ] || { echo "no $TXT - pull the ring first" >&2; exit 1; }

echo "== identity =="
cmp "$RAW" work/ring62.raw && echo "IDENTICAL TO ring62 - not a new boot!" || echo "differs from ring62 = new boot"
wc -c "$RAW" "$TXT"

echo "== 1. key lines (arming health = the (N clients) count) =="
grep -n "SWEET HID: powerkey\|SWEET HID: key 0x" "$TXT" | cut -c1-120

echo "== 2. event size / sender (60 B expected for a keyboard event) =="
grep -n "SWEET HID: event size=" "$TXT" | cut -c1-90

echo "== 3. queue traffic (enq delta, drop, head==tail) =="
grep -n "SWEET HID: queue stats" "$TXT" | cut -c1-120

echo "== 4. display / dispatch =="
grep -nE "SWEET FB: (display|swap)|display-off request ignored" "$TXT" | cut -c1-100

echo "== 5. sampler (first non-Setup target ever) =="
grep -n "^SMP " "$TXT" | cut -c1-110 | head -40

echo "== 6. acceptance / AKS =="
printf 'AKS sel 9/12 lines: '; grep -cE "^SWEET AKS:.*sel (9|12)( |$)" "$TXT" || true
grep -n "SWEET AKS" "$TXT" | grep -E "sel (9|12)( |$)" | cut -c1-100 || true

echo "== 7. touch IC live? (T20 confound check, must be > 0) =="
printf 'PRA touch lines: '; grep -c "PRA touch" "$TXT" || true
grep -n "app mode confirmed\|reports=" "$TXT" | tail -5 | cut -c1-110 || true

echo "== 8. health =="
printf 'panic: '; grep -c "panic" "$TXT" || true
printf 'exec SpringBoard: '; grep -c "exec SpringBoard" "$TXT" || true
printf 'exec backboardd: '; grep -c "exec backboardd" "$TXT" || true
grep -n "PRA LOG: strat flush" "$TXT" | tail -1 | cut -c1-100 || true
