# ring31-notes.md — peers boot (0173-peers kernel, pre-tweak root)

Kernel: same 0173 binary, cmdline sweetsample extended to
SpringBoard,backboardd,Setup,runningboardd,launchd,notifyd (image
out/pra-xnu-0173-peers.img sha fc5d686c…). Ring31 pulled 2026-11-16 ~20:10
(work/ring31.txt; raw research/pra-artifacts/ring31.bin). Current-boot
fragment: slide 0x2be9c000, Setup[425].

## Answer to the circular-vs-missing-waker question

**The missing waker is launchd itself, wedged in sync().** launchd[1] t2
(th=0xfffffff29958d430) sits in st=0x9 (TH_WAIT|TH_UNINT — uninterruptible)
with cont=0x0 (stack-kept block) and upcb pc = the BSD 36 `sync` stub
(0x1c2614048, decoded MOVZ x16,#36;SVC;B.cond) from sample 2 on — an
uninterruptible `sync()` blocked in the HFS write path since ~4 min into the
boot, exactly during the churn/migration write storm. launchd's OTHER
threads keep spawning (the churn continues), but pid 1 carrying an
uninterruptible VFS block explains the world-wide receive parks.

- runningboardd's own thread (th=…6e4820, n=6) is itself parked in mach_msg2
  port receive (cont=_ipc_mqueue_receive_continue, wq=0xfffffff4661e0408) —
  consistent with ring30's unanswered Setup->runningboardd.
- backboardd's two receive parks recur (wq 0xfffffff4661e05b8/06d8 — this
  boot's heap layout differs from ring30's, as expected).
- The rest of the sampled threads sit in BENIGN parks: sigsuspend_nocancel
  (BSD 410, cont=__sleep_continue), semaphore_wait_trap (-36,
  cont=_semaphore_wait_continue), workq GCD parks — daemon idlers.
- One ring31 oddity: a launchd thread recorded st=0x4 (TH_RUN) at the sync
  stub in one sample (glue-prone record; the UNINT record is the trusted one).
- PRA MSG[66]: runningboardd -> Setup id=0x10000000 — this boot's reply DID
  arrive (ring30's msg 69 never got one), so early IPC reached further; the
  wedge still froze the pipeline later.

## Root cause (working theory)

The sweet_hfs/eMMC write path intermittently wedges under write load (ring30
stats: per-command maxes 1.1-14.3 s during bring-up; 14x "write failed 16" =
EBUSY). A stuck buffer makes sync() (launchd) or any UNINT VFS waiter
(ring30: SpringBoard t0 in mkdirat) block forever; everyone waiting on those
processes parks in mach_msg2 receive. The donor never hit it on the S8
(faster storage, and their root tweaks cut the write storm).

## Fix applied for the next boot (tweaked root, userdata restaged)

tools/sweet-root-tweaks.py applied to the staged image (user-run sudo block):
launchd.plist 7x _PanicOnCrash->_PanicOnCrasX + 2 CommCenter jobs removed,
/private/var/containers created, real purplebuddy Setup bypass
(SetupDone/SetupFinishedAllSteps/SetupVersion 11, daemonize off, mini-buddy
off), SpringBoard BKNoWatchdogs, VirtualAudio disabled, MediaToolbox
StartRecorderServer off, migration prefs completed. DataMigration and the
Setup wizard were the two big early-boot write storms — both now bypassed.
Build flow fixed to always apply them (c3bace1). Remaining churn:
fairplayd.H2/bluetoothd/nanotimekitcompaniond jobs are still in launchd.plist
(the donor's script only removes CommCenter) — EPERM'd by praexecskip before
any image read; candidates for a follow-up launchd.plist cleanup.

Success signal for the next boot: SWEET FB swap counts past 7, and/or the
lock screen on the panel. If sync() wedges again: 0175 = rate-limited print
in the sweet_hfs write path when a buffer/journal lock is held >10 s.
