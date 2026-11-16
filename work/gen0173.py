#!/usr/bin/env python3
"""gen0173.py (v2) - build xnu/patches/0173-pra-stuck-thread-reporter.patch
deterministically. Local git apply of the full stack is broken (git 2.56
false-skips hunks with rc=0), so this script replays the exception.c hunks
itself with strict context matching.

1. Extract PRISTINE osfmk/kern/exception.c from the xnu tarball.
2. Replay every patch in stack order that touches it:
   0043, 0051, 0053, 0054, 0055, 0066, 0111 (grep-verified list).
3. Insert the 0173 kernel-state hunk (th/st/we/wq + kernel fp chain).
4. Emit unified diff (all-patches state -> +0173).
5. Verify with git apply + GNU patch --fuzz=0 against the all-patches state.
"""
import tarfile, re, difflib, subprocess, os, tempfile, shutil, glob

REPO = "/home/kamion008/Ai/ios/ios-pra"
TGZ = "/tmp/ci173/t.tgz"
MEM = "xnu-xnu-8796.141.3/osfmk/kern/exception.c"
OUT = f"{REPO}/xnu/patches/0173-pra-stuck-thread-reporter.patch"
PATCHDIR = f"{REPO}/xnu/patches"
TARGET = "osfmk/kern/exception.c"

with tarfile.open(TGZ) as tf:
    pristine = tf.extractfile(MEM).read().decode("utf-8")
print(f"[1] pristine exception.c: {len(pristine.splitlines())} lines")

def parse_hunks(path, want_file):
    """Return [(old_start, old_count, new_count, body_lines)] for want_file."""
    txt = open(path, encoding="utf-8", errors="surrogateescape").read().splitlines()
    cur = None  # current file's section
    hunks, in_hunk = [], None
    hdr_re = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    i = 0
    while i < len(txt):
        l = txt[i]
        if l.startswith("--- a/") or l.startswith("--- /dev/null"):
            m2 = re.match(r"--- a/(\S+)", l)
            cur = m2.group(1) if m2 else None
            in_hunk = None
        elif l.startswith("@@") and cur == want_file:
            m = hdr_re.match(l)
            assert m, l
            os_, oc = int(m.group(1)), int(m.group(2) or 1)
            ns_, nc = int(m.group(3)), int(m.group(4) or 1)
            body = []
            i += 1
            oc_seen = nc_seen = 0
            while i < len(txt) and (oc_seen < oc or nc_seen < nc):
                bl = txt[i]
                if bl.startswith("@@") or bl.startswith("--- a/") or \
                   bl.startswith("diff --git"):
                    break
                body.append(bl)
                if bl.startswith(" "):
                    oc_seen += 1; nc_seen += 1
                elif bl.startswith("-"):
                    oc_seen += 1
                elif bl.startswith("+"):
                    nc_seen += 1
                elif bl.startswith("\\"):
                    pass
                else:
                    break
                i += 1
            assert oc_seen == oc and nc_seen == nc, \
                f"{path}: hunk parse {oc_seen}/{oc} {nc_seen}/{nc}"
            hunks.append((os_, oc, nc, body))
            continue
        i += 1
    return hunks

def apply_hunks(src_lines, hunks, tag):
    delta = 0
    for (os_, oc, nc, body) in hunks:
        old = [l[1:] for l in body if l.startswith((" ", "-"))]
        pos = os_ - 1 + delta
        match = all(src_lines[pos + k].rstrip() == old[k].rstrip()
                    for k in range(oc))
        if not match:
            found = -1
            for s in range(max(0, pos - 40), min(len(src_lines), pos + 40)):
                if all(src_lines[s + k].rstrip() == old[k].rstrip()
                       for k in range(oc)):
                    found = s
                    break
            assert found >= 0, f"{tag} hunk @{os_}: context not found"
            print(f"    {tag} hunk @{os_}: found at shifted pos {found+1} "
                  f"(expected {pos+1})")
            pos = found
        new = [l[1:] for l in body if l.startswith((" ", "+"))]
        src_lines = src_lines[:pos] + new + src_lines[pos + oc:]
        delta += nc - oc
    return src_lines

patches = sorted(glob.glob(f"{PATCHDIR}/*.patch"),
                 key=lambda p: int(re.search(r"(\d{4})", p).group(1)))
state = pristine.splitlines()
for p in patches:
    if "0173-" in p:
        continue
    hs = parse_hunks(p, TARGET)
    if not hs:
        continue
    n = os.path.basename(p)
    print(f"[2] {n}: {len(hs)} exception.c hunk(s)")
    state = apply_hunks(state, hs, n)
print(f"[2] after all patches: {len(state)} lines")
assert "sweet_sample_task(const char *name, int pid, task_t task)" in "\n".join(state)

# --- insert the 0173 edit ---
final_lines = list(state)
whole = "\n".join(final_lines)
bi = next(i for i, l in enumerate(final_lines) if re.match(r"\t\tchar line\[\d+\];$", l))
old_buf = final_lines[bi]
final_lines[bi] = "\t\tchar line[640];"
print(f"[3] buffer {old_buf.strip()} -> line[640] at line {bi+1}")
anchor_pat = ["\t\t\tfp = frame[0];", "\t\t}", "\t\tprintf(\"%s\\n\", line);"]
ai = next((i for i in range(bi, bi + 120)
           if final_lines[i:i+3] == anchor_pat), -1)
assert ai > 0, "user-bt loop end anchor not found"
print(f"[3] anchor at line {ai+1}")
INSERT = """\t\t/*
\t\t * 0173: kernel-side context of the same thread. state/wait_event/waitq
\t\t * say HOW it is parked (wait_event is an event64_t value, 0 =
\t\t * NO_EVENT64 for a mach_msg2 port receive; waitq names the wait queue -
\t\t * for a port receive it is the port's embedded ip_waitq, so the owning
\t\t * port is wq - offsetof(ipc_port, ip_waitq), computed offline).
\t\t * cont names the continuation a stackless block resumes (mach_msg2
\t\t * receive blocks at ipc_mqueue_receive_continue with the stack freed,
\t\t * kernel_stack == 0). The kernel fp chain is only readable when the
\t\t * stack was kept (kernel_stack != 0): read the per-thread kernel saved
\t\t * state (thread_get_kernel_state()->machine.ss, the same source
\t\t * machine_trace_thread64 uses for blocked threads) and walk fp bounded
\t\t * to this thread's own kernel stack, 8-aligned, downward.
\t\t */
\t\tvm_offset_t ksb = (vm_offset_t)thread->kernel_stack;
\t\tuint64_t kfp = 0, klr = 0;

\t\tn += snprintf(line + n, sizeof(line) - n,
\t\t    " th=0x%llx st=0x%x we=0x%llx wq=0x%llx cont=0x%llx kbt",
\t\t    (uint64_t)thread, (unsigned int)thread->state,
\t\t    (uint64_t)thread->wait_event, (uint64_t)thread->waitq.wq_q,
\t\t    (uint64_t)thread->continuation);
\t\tif (n >= (int)sizeof(line)) {
\t\t\tn = (int)sizeof(line) - 1;
\t\t\tline[n] = '\\0';
\t\t}
\t\tif (ksb != 0) {
\t\t\tarm_kernel_saved_state_t *kg =
\t\t\t    &thread_get_kernel_state(thread)->machine.ss;
\t\t\tkfp = kg->fp;
\t\t\tklr = kg->lr;
\t\t}
\t\tif (klr != 0) {
\t\t\tn += snprintf(line + n, sizeof(line) - n, " 0x%llx", klr);
\t\t}
\t\tfor (int i = 0; i < 10 && kfp != 0 && (kfp & 7) == 0 &&
\t\t    kfp > (uint64_t)ksb && kfp < (uint64_t)(ksb + kernel_stack_size) &&
\t\t    kfp + sizeof(uint64_t[2]) <= (uint64_t)(ksb + kernel_stack_size) &&
\t\t    n < (int)sizeof(line) - 24; i++) {
\t\t\tuint64_t frame[2];

\t\t\tmemcpy(frame, (const void *)kfp, sizeof(frame));
\t\t\tn += snprintf(line + n, sizeof(line) - n, " 0x%llx", frame[1]);
\t\t\tif (frame[0] <= kfp) {
\t\t\t\tbreak;
\t\t\t}
\t\t\tkfp = frame[0];
\t\t}
"""
final_lines = final_lines[:ai+2] + INSERT.splitlines() + final_lines[ai+2:]
print(f"[3] no include added: kern/thread.h -> arm/thread.h:84 already pulls "
      f"kern/thread_kernel_state.h under MACH_KERNEL_PRIVATE (its guard macro "
      f"is never #defined, so a second include would redefine the struct); "
      f"final {len(final_lines)} lines")

# --- emit diff ---
d = list(difflib.unified_diff(state, final_lines,
    fromfile="a/osfmk/kern/exception.c", tofile="b/osfmk/kern/exception.c", n=3, lineterm=""))
header = """pra: 0173 - sampler prints kernel-side wait state per thread

The ring29 census (work/census29.md, 537 thread records, 21 distinct PCs)
refuted "majority trap -13": zero samples sit at
task_dyld_process_info_notify_get; the parked threads are mach_msg2_trap
(-47, 268), workq_kernreturn (368, 76), sys_ulock_wait (515, 27) and
kevent_id (375, 16), and 22 samples have pc=0. The mach_vm_deallocate probe
planned as 0173 hunk (a) measures a trap that never appears - dropped.

What the sampler could not answer is WHY the kernel parks these threads.
The user-only backtrace ends at the syscall stub. This patch extends every
per-thread "SMP" line with:
  th=0x..    the thread pointer
  st=0x..    thread->state (TH_WAIT etc., osfmk/kern/thread.h)
  we=0x..    thread->wait_event (event64_t value; 0 = NO_EVENT64 = a port
             receive in mach_msg2; the handoff's "string" reading is wrong)
  wq=0x..    thread->waitq.wq_q - for a port receive this is the port's
             embedded ip_waitq, so the owning port is
             wq - offsetof(struct ipc_port, ip_waitq) (ipc_port.h:318),
             resolved offline against the CI kernel + headers
  kbt 0x..   kernel fp chain from the per-thread kernel saved state
             (thread_get_kernel_state()->machine.ss, the same source
             machine_trace_thread64 uses for blocked threads,
             osfmk/kdp/ml/arm/kdp_machdep.c:364), bounded to the thread's
             own kernel_stack, 8-byte aligned, strictly downward.
Line buffer 220 -> 640 with explicit truncation clamps (the old loop's
fixed 20-char margin does not cover the new ~70-char append).

Marker asserted in CI (Verify): 'cont=0x%llx kbt'.
"""
with open(OUT, "w", encoding="utf-8", errors="surrogateescape") as f:
    f.write(header + "\n".join(d) + "\n")
nm = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
np_ = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
print(f"[4] wrote {OUT} (-{nm}/+{np_})")

# --- verify: scratch repo at the all-patches state, apply, compare ---
scratch = tempfile.mkdtemp(prefix="v0173")
bp = os.path.join(scratch, TARGET)
os.makedirs(os.path.dirname(bp))
open(bp, "w").write("\n".join(state) + "\n")
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
applied = open(bp).read()
ok = applied == "\n".join(final_lines) + "\n"
print(f"[5] applied == expected final: {ok}")
assert ok
shutil.rmtree(scratch)
print("[6] VERIFY PASS: 0173 applies to the fully-replayed exception.c state")
