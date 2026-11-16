#!/usr/bin/env python3
"""gen0175.py - build xnu/patches/0175-pra-block-caller-frame.patch.

0175: record the block caller's frame in thread_block_reason (the machine
saved-state fp chain cannot cross the context switch - ring32's walks ended
at _thread_invoke), print it as blr= in every SMP line, and for stack-kept
blocks walk the kernel fp chain from the recorded caller frame instead of
machine.ss. Names the exact wedged VFS/journal caller for UNINT threads.

Replay lineage (all from the pristine tarball):
- osfmk/kern/thread.h: NO prior patches (verified: no patch modifies it).
- osfmk/kern/sched_prim.c: NO prior patches (verified).
- osfmk/kern/exception.c: 0043,0051,0053,0054,0055,0066,0111 + 0173.
"""
import tarfile, re, difflib, subprocess, os, tempfile, shutil, glob

REPO = "/home/kamion008/Ai/ios/ios-pra"
TGZ = "/tmp/ci173/t.tgz"
P = f"{REPO}/xnu/patches"
OUT = f"{P}/0175-pra-block-caller-frame.patch"

def tar_read(member):
    with tarfile.open(TGZ) as tf:
        return tf.extractfile(f"xnu-xnu-8796.141.3/{member}").read().decode("utf-8")

def parse_hunks(path, want_file):
    txt = open(path, encoding="utf-8", errors="surrogateescape").read().splitlines()
    cur = None; hunks = []
    hdr = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    i = 0
    while i < len(txt):
        l = txt[i]
        if l.startswith("--- a/") or l.startswith("--- /dev/null"):
            m2 = re.match(r"--- a/(\S+)", l); cur = m2.group(1) if m2 else None
        elif l.startswith("@@") and cur == want_file:
            m = hdr.match(l)
            os_, oc = int(m.group(1)), int(m.group(2) or 1)
            ns_, nc = int(m.group(3)), int(m.group(4) or 1)
            body = []; i += 1; a = b = 0
            while i < len(txt) and (a < oc or b < nc):
                bl = txt[i]
                if bl.startswith("@@") or bl.startswith("--- a/") or bl.startswith("diff --git"):
                    break
                body.append(bl)
                if bl.startswith(" "): a += 1; b += 1
                elif bl.startswith("-"): a += 1
                elif bl.startswith("+"): b += 1
                elif bl.startswith("\\"): pass
                else: break
                i += 1
            hunks.append((os_, oc, nc, body)); continue
        i += 1
    return hunks

def apply_hunks(src, hunks, tag):
    delta = 0
    for (os_, oc, nc, body) in hunks:
        old = [l[1:] for l in body if l.startswith((" ", "-"))]
        pos = os_ - 1 + delta
        if not all(src[pos+k].rstrip() == old[k].rstrip() for k in range(oc)):
            found = -1
            for s in range(max(0, pos-60), min(len(src), pos+60)):
                if all(src[s+k].rstrip() == old[k].rstrip() for k in range(oc)):
                    found = s; break
            assert found >= 0, f"{tag} hunk @{os_}: context not found"
            pos = found
        new = [l[1:] for l in body if l.startswith((" ", "+"))]
        src = src[:pos] + new + src[pos+oc:]
        delta += nc - oc
    return src

# ---- thread.h: append two fields at struct thread end ----
th = tar_read("osfmk/kern/thread.h").splitlines()
bi = next(i for i, l in enumerate(th)
          if l == "\tstruct knote            *ith_knote;         /* knote fired for rcv */")
assert th[bi+2] == "};", repr(th[bi+1:bi+3])
th_new = th[:bi+2] + [
    "\t/* 0175: block-caller frame recorded in thread_block_reason so the",
    "\t * sampler can walk the pre-switch caller chain (the machine saved-",
    "\t * state fp chain does not survive the context switch: ring32 walks",
    "\t * ended at _thread_invoke). */",
    "\tuint64_t                pra_block_fp;",
    "\tuint64_t                pra_block_lr;",
    "};",
] + th[bi+3:]
print(f"[1] thread.h: +2 fields at line {bi+2} (pristine {len(th)} lines)")

# ---- sched_prim.c: record in thread_block_reason ----
sp = tar_read("osfmk/kern/sched_prim.c").splitlines()
anchor = ["\tself->continuation = continuation;", "\tself->parameter = parameter;"]
ai = next(i for i in range(len(sp)) if sp[i:i+2] == anchor)
sp_new = sp[:ai+2] + [
    "\t/* 0175: record the block caller's frame for the sampler (the machine",
    "\t * saved-state fp chain does not survive the context switch). */",
    "\tself->pra_block_fp = (uint64_t)__builtin_frame_address(0);",
    "\tself->pra_block_lr = (uint64_t)__builtin_return_address(0);",
] + sp[ai+2:]
print(f"[2] sched_prim.c: block-caller record after line {ai+2} (pristine {len(sp)} lines)")

# ---- exception.c: replay lineage, then extend the sampler ----
ex = tar_read("osfmk/kern/exception.c").splitlines()
patches = sorted(glob.glob(f"{P}/*.patch"),
                 key=lambda p: int(re.search(r"(\d{4})", p).group(1)))
for p in patches:
    if "0175-" in p or "0173-" in p:
        continue
    hs = parse_hunks(p, "osfmk/kern/exception.c")
    if hs:
        ex = apply_hunks(ex, hs, os.path.basename(p))
base = list(ex)   # true pre-0173 state
ex = apply_hunks(ex, parse_hunks(f"{P}/0173-pra-stuck-thread-reporter.patch",
                                 "osfmk/kern/exception.c"), "0173")
base = apply_hunks(base, parse_hunks(f"{P}/0173-pra-stuck-thread-reporter.patch",
                                     "osfmk/kern/exception.c"), "0173-base")
print(f"[3] exception.c base (post-0173): {len(ex)} lines")

# extend the sampler: blr= field + pra_block_fp walk for stack-kept blocks.
# Every anchor must be UNIQUE in the post-0173 file; assert it.
WALK_OLD = (
    "\t\tif (ksb != 0) {",
    "\t\t\tarm_kernel_saved_state_t *kg =",
    "\t\t\t    &thread_get_kernel_state(thread)->machine.ss;",
    "\t\t\tkfp = kg->fp;",
    "\t\t\tklr = kg->lr;",
    "\t\t}",
)
occ = sum(1 for i in range(len(ex)) if tuple(ex[i:i+len(WALK_OLD)]) == WALK_OLD)
assert occ == 1, f"walk anchor not unique: {occ}"
oi = next(i for i in range(len(ex)) if tuple(ex[i:i+len(WALK_OLD)]) == WALK_OLD)
ex[oi:oi+len(WALK_OLD)] = (
    "\t\tif (ksb != 0 && thread->pra_block_fp != 0) {",
    "\t\t\t/* 0175: the block caller's frame - the real pre-switch chain. */",
    "\t\t\tkfp = thread->pra_block_fp;",
    "\t\t\tklr = thread->pra_block_lr;",
    "\t\t} else if (ksb != 0) {",
) + WALK_OLD[1:]
print(f"[3] sampler walk prefers pra_block_fp (stack-kept blocks)")
FMT_OLD = '\t\t    " th=0x%llx st=0x%x we=0x%llx wq=0x%llx cont=0x%llx kbt",'
assert sum(1 for l in ex if l == FMT_OLD) == 1, "format anchor not unique"
fi = next(i for i, l in enumerate(ex) if l == FMT_OLD)
ex[fi] = '\t\t    " th=0x%llx st=0x%x we=0x%llx wq=0x%llx cont=0x%llx blr=0x%llx kbt",'
# args: thread, state, wait_event, wq_q, continuation, pra_block_lr
ARG_CONT = "\t\t    (uint64_t)thread->continuation);"
assert sum(1 for l in ex if l == ARG_CONT) == 1, "cont-arg anchor not unique"
ci = next(i for i, l in enumerate(ex) if l == ARG_CONT)
ex[ci] = "\t\t    (uint64_t)thread->continuation,"
ex.insert(ci + 1, "\t\t    thread->pra_block_lr);")
print(f"[3] blr= added (arg order: cont then pra_block_lr)")

d1 = difflib.unified_diff(th, th_new, fromfile="a/osfmk/kern/thread.h",
                          tofile="b/osfmk/kern/thread.h", n=3, lineterm="")
d2 = difflib.unified_diff(sp, sp_new, fromfile="a/osfmk/kern/sched_prim.c",
                          tofile="b/osfmk/kern/sched_prim.c", n=3, lineterm="")
d3 = difflib.unified_diff(base, ex, fromfile="a/osfmk/kern/exception.c",
                          tofile="b/osfmk/kern/exception.c", n=3, lineterm="")
header = """pra: 0175 - sampler records and walks the block caller's frame

ring32: launchd t1 (sync) and SpringBoard t0 (pager fault on a shared-cache
page) sit UNINTERRUPTIBLY on the SAME wait event (we=0xfffffff6390dce08) -
one wedged FS object blocks both. The 0173 kbt walk cannot cross the context
switch: machine.ss's fp chain ends at _thread_invoke, so the pre-block
caller chain (thread_block_reason -> msleep -> the wedged VFS/journal site)
was unreachable.

This patch: thread_block_reason records the caller's fp/lr into two new
thread fields (pra_block_fp/lr) before the switch; the sampler prints the
caller lr as blr= on every SMP line and, for stack-kept blocks, walks the
kernel fp chain from pra_block_fp (which crosses into the real pre-block
callers: msleep -> VFS -> the wedged site). Continuation blocks still print
cont only (their stack is freed; walking it would read the next thread's
stack).

Marker asserted in CI (Verify): 'blr=0x%llx kbt'.
"""
with open(OUT, "w", encoding="utf-8", errors="surrogateescape") as f:
    f.write(header + "\n".join(list(d1) + list(d2) + list(d3)) + "\n")
print(f"[4] wrote {OUT}")

# ---- verify: scratch repo with the replayed bases, git apply + GNU patch ----
scratch = tempfile.mkdtemp(prefix="v0175")
for path, content in (("osfmk/kern/thread.h", "\n".join(th) + "\n"),
                      ("osfmk/kern/sched_prim.c", "\n".join(sp) + "\n"),
                      ("osfmk/kern/exception.c", "\n".join(base) + "\n")):
    fp = os.path.join(scratch, path)
    os.makedirs(os.path.dirname(fp), exist_ok=True)
    open(fp, "w").write(content)
subprocess.run(["git", "init", "-q", scratch], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.email", "v@v"], check=True)
subprocess.run(["git", "-C", scratch, "config", "user.name", "v"], check=True)
subprocess.run(["git", "-C", scratch, "add", "-A"], check=True)
subprocess.run(["git", "-C", scratch, "commit", "-qm", "base"], check=True)
r0 = subprocess.run(["git", "-C", scratch, "apply", "--check", "-v", OUT],
                    capture_output=True, text=True)
print(f"[5] git apply --check rc={r0.returncode}")
for l in (r0.stdout + r0.stderr).splitlines():
    if any(k in l for k in ("Skipped", "error", "Checking")):
        print(f"    {l}")
assert r0.returncode == 0 and "Skipped" not in (r0.stdout + r0.stderr)
r2 = subprocess.run(["patch", "-p1", "--fuzz=0", "--dry-run", "-i", OUT],
                    cwd=scratch, capture_output=True, text=True)
print(f"[5] GNU patch --fuzz=0 --dry-run rc={r2.returncode}")
assert r2.returncode == 0, r2.stdout + r2.stderr
r = subprocess.run(["git", "-C", scratch, "apply", "-v", OUT],
                   capture_output=True, text=True)
print(f"[5] git apply rc={r.returncode}")
assert r.returncode == 0 and "Skipped" not in (r.stdout + r.stderr)
for path, expect in (("osfmk/kern/thread.h", "\n".join(th_new) + "\n"),
                     ("osfmk/kern/sched_prim.c", "\n".join(sp_new) + "\n"),
                     ("osfmk/kern/exception.c", "\n".join(ex) + "\n")):
    got = open(os.path.join(scratch, path)).read()
    assert got == expect, f"{path} mismatch"
    print(f"[5] {path}: applied == expected")
shutil.rmtree(scratch)
print("[6] VERIFY PASS: 0175 applies to the replayed bases")
