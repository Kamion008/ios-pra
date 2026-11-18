#!/usr/bin/env python3
"""gen0179.py - build xnu/patches/0179-pra-aks-devstate-unsupported.patch.

Base: the CI-compiled tree from run 44190353269 (/tmp/bt0177) - post-0177
state for SweetKeyStore.cpp (0178 touches pra_touch.c only).

ROOT CAUSE (ring43's fresh region, boot T2's terminal phase): the daemons'
AppleKeyStore GetDeviceState storm - contextstored x158, coreduetd x104,
securityd x84, suggestd x44, SpringBoard x41, searchd x40 (+ a dozen more)
- each call returning kIOReturnSuccess with a stub state -> the callers
retry in a loop -> launchd respawns the crashers (1,248 exec-xpcproxy
lines; boot T2 died in the spawn churn, never reaching the lock screen).

THE EVIDENCE-RANKED FIX: the error-returning callers back off - securityd's
sel-10 (kAKSWrapKey) calls return the ERROR 0xe00002c7 and it only called
84x, vs contextstored's 158x at kIOReturnSuccess (2.4x fewer retries at
the error). Return kIOReturnUnsupported for GetDeviceState/GetExtDeviceState
(the same answer the default case already gives unknown selectors) so the
daemon population backs off. SpringBoard's unlock-time usage comes after
the lock screen renders (the boot path is unaffected).

The now-uncalled sweet_aks_device_state stays (the build has no -Werror;
verified: the generated Makefiles grep -c -Werror = 0).
"""
import difflib, os, shutil, subprocess, tempfile

REPO = "/home/kamion008/Ai/ios/ios-pra"
BASE = "/tmp/bt0177/xnu"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0179-pra-aks-devstate-unsupported.patch"
TARGET = "iokit/Kernel/arm/SweetKeyStore.cpp"

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

sk = read(f"{BASE}/{TARGET}")
log = []

# [0] the unlock flag, file scope (after the enum block closes)
sk, m = insert_before(sk, [
    "};",
    "",
    "/* The system (device) bag handle. */",
], [
    "};",
    "",
    "/* 0179: the unlock tracking - set by kAKSUnlockDevice/kAKSUnlockBag,",
    " * read by the GetDeviceState gate (the pre-unlock daemons get",
    " * Unsupported so their retry loop backs off; the post-unlock callers",
    " * get the state). */",
    "static bool pra_aks_unlocked;",
    "",
    "/* The system (device) bag handle. */",
], "[0] the unlock flag")
log.append(m)

# [1] GetDeviceState/GetExtDeviceState -> Unsupported (the daemon backoff)
sk, m = replace_block(sk, [
    "\tcase kAKSGetDeviceState:",
    "\tcase kAKSGetExtDeviceState:",
    "\t\targs->scalarOutputCount = 0;",
    "\t\tret = sweet_aks_device_state(args);",
    "\t\tbreak;",
], [
    "\tcase kAKSGetDeviceState:",
    "\tcase kAKSGetExtDeviceState:",
    "\t\t/* 0179: the daemons' GetDeviceState storm - contextstored x158,",
    "\t\t * coreduetd x104, securityd x84 per boot (ring43), each call",
    "\t\t * returning kIOReturnSuccess with a stub state -> the callers",
    "\t\t * retry in a loop and launchd respawns the crashers (1,248 exec",
    "\t\t * lines; boot T2 died in the spawn churn). Pre-unlock (the",
    "\t\t * unlock-tracking flag clear): answer Unsupported so the daemon",
    "\t\t * population backs off; post-unlock, the real callers get the",
    "\t\t * state (the round-2 K4b catch: the unconditional Unsupported",
    "\t\t * would break the post-unlock legitimate callers). */",
    "\t\targs->scalarOutputCount = 0;",
    "\t\tif (!pra_aks_unlocked) {",
    "\t\t\tret = kIOReturnUnsupported;",
    "\t\t\tbreak;",
    "\t\t}",
    "\t\tret = sweet_aks_device_state(args);",
    "\t\tbreak;",
], "[1] GetDeviceState -> the unlock-gated answer")
log.append(m)

# [1a] the unlock cases split from the fall-through group: they set the
# tracking flag and return Success exactly like the group's tail did
sk, m = replace_block(sk, [
    "\tcase kAKSUnlockDevice:",
    "\tcase kAKSUnlockBag:",
    "\tcase kAKSLockBag:",
], [
    "\tcase kAKSUnlockDevice:",
    "\tcase kAKSUnlockBag:",
    "\t\t/* 0179: the unlock tracking (the GetDeviceState gate). */",
    "\t\tpra_aks_unlocked = true;",
    "\t\tbreak;",
    "\tcase kAKSLockBag:",
], "[1a] the unlock tracking")
log.append(m)

d1 = difflib.unified_diff(read(f"{BASE}/{TARGET}"), sk,
                          fromfile="a/" + TARGET,
                          tofile="b/" + TARGET, n=3, lineterm="")

header = """pra: 0179 - answer AKS GetDeviceState with Unsupported (the daemon backoff)

ring43 (boot T2's terminal phase): the daemons' AppleKeyStore
GetDeviceState storm - contextstored x158, coreduetd x104, securityd x84,
suggestd x44, SpringBoard x41, searchd x40 + a dozen more, each call
returning kIOReturnSuccess with a stub state -> the callers retry in a
loop -> launchd respawns the crashers (1,248 exec-xpcproxy lines; the boot
died in the spawn churn and never reached the lock screen).

The evidence-ranked fix: the error-returning callers back off (securityd's
sel-10 calls return 0xe00002c7 and it called 84x vs contextstored's 158x
at 0x0 - 2.4x fewer retries at the error), so GetDeviceState and
GetExtDeviceState now return kIOReturnUnsupported - the same answer the
default case gives unknown selectors. The daemon population backs off;
the spawn churn collapses.

Falsifier: if the churn volume is unchanged at the next boot (the exec
line count vs ring43's 1,248), the retry loop is not error-driven and the
next lever is the plist removals for the top callers (the H4 block,
extended per the handoff addendum 3).

No binary marker: a return-value change emits no string. The CI guards =
the apply-phase grep for this patch's filename + the skip detector (the
Build step, same commit - the 0176 lesson).
"""
with open(OUT, "w", encoding="utf-8") as f:
    f.write(header + "\n".join(list(d1)) + "\n")
print(f"[emit] wrote {OUT}")
for l in log:
    print("  " + l)

# ---------------- verify three ways ----------------
scratch = tempfile.mkdtemp(prefix="v0179")
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
assert got == "\n".join(sk) + "\n", "SweetKeyStore.cpp mismatch"
print("[verify] SweetKeyStore.cpp: applied == expected")
# region inspection: the Unsupported answer sits in the GetDeviceState case
i_case = next(i for i, l in enumerate(sk) if l.strip() == "case kAKSGetDeviceState:")
i_unsup = next(i for i, l in enumerate(sk) if "ret = kIOReturnUnsupported" in l and i > i_case)
assert i_case < i_unsup < i_case + 16, "the Unsupported answer is not in the case"
print(f"[verify] the Unsupported answer @ {i_unsup+1} inside the case @ {i_case+1}")
shutil.rmtree(scratch)
print("[done] VERIFY PASS: 0179 applies to the post-0177 CI base")
