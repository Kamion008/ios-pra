# Session 2026-11-16 (task D): AGENTS.md rewrite + transcript disposition

Task D only (per HANDOFF_2026-11-16.md session brief). No phone contact, no
flashes, no eMMC writes. Tasks A/B/C not started (other sessions).

## Done
1. Committed the working-tree-only ADDENDUM of HANDOFF_2026-11-16.md
   (commit 8fe97c2). It was uncommitted although this session's task list
   derives from it.
2. Rewrote AGENTS.md to 59 lines (<60 required), commit cb583bb (amended once
   to get 60→59). Content: project summary, repo layout, build/package/flash/
   ring commands, cmdline-gate rules, patch hygiene, safety rules, pointer to
   HANDOFF_2026-11-16.md. No status, blockers or theories.
3. Committed the untracked transcript after redaction (commit dda5164):
   - pra_session_compact_transcript.md (5623 lines, reconstructed from
     slim.jsonl, which no longer exists anywhere on disk — sole copy).
   - Contained real device serial `57U7N...` (redacted in this note) ×7
     (old lines 120/132/143/2121/2141/3572/5509) — serials never go in git
     (HANDOFF §7). sed → PRA_SERIAL_REDACTED; post-check: 0 serial hits, 8
     PRA_SERIAL_REDACTED (7 + banner). Residual `[A-Z0-9]{16,}` scan: only
     0000000000500000 (payload offset) + APPLEVIRTUALPLATFORM (name) — clean.
   - 7-line banner marks it HISTORICAL (0153-era) and superseded: stock-GPT
     preserved → later resized (user-approved, research/gpt/); Setup intact →
     later SetupDone bypass; -noprogress → later progress bar enabled.

## Evidence pointers for AGENTS.md claims (verified this session)
- 11-arg gate: tools/pra_package.sh:87-99 and tools/pra_flash_skip.sh:60-66
  print "cmdline OK: all 11 critical args present"; old AGENTS.md said 12.
- Flash target p27 only: tools/pra_flash_skip.sh:7-10,24,94,96 (dd
  bs=1048576 seek=$SEEK_MIB, readback verify skip=753664).
- CI dispatch: tools/pra_ci.sh:5,19; artifact name xnu-kernel from
  HANDOFF §8 (gh run download … -n xnu-kernel).
- Ring read: tools/pra_readlog.sh:21-29 (dd bs=512 skip=$LBA, TXT env);
  LBA 794623 from HANDOFF §6.3/§8.
- Old-AGENTS cmdline had sweetsample=Setup and was stale per HANDOFF STALE
  INSTRUCTIONS #3 — new AGENTS.md does NOT duplicate the cmdline; it points
  at the default inside tools/pra_package.sh:54 to kill the drift trap.

## Discrepancies found vs the handoff (reported, not smoothed over)
- work/ lacks sym29.py / sym29b.py / sym24.py / stubfind.py / imglist.py
  that HANDOFF §8 lists (they were /tmp-resident and died). Tasks A/B must
  recreate them from §5's method. work/ actually contains only: ring28.txt,
  ring29.txt, ring26-panic-screen.txt, 0173-wip.diff.
- work/census29.py appeared untracked DURING this session — not created by
  this session (possibly a concurrent task-A session). Left untouched.
- shim/pra/out0151|0153|0154/ remain untracked (old build outputs, HANDOFF
  §8). Not gitignored (only shim/pra/out*/xnu patterns are). Left for the
  user/next session: ignore, gitignore, or delete with approval.

## Refutation-rule note
Task D is mechanical text work whose output IS the evidence (line counts,
grep counts, diffs) — no flash/patch/diagnosis decision, so no refutation
round needed (per the brief's skip rule for mechanical steps).

## Commits this session
- 8fe97c2 docs: commit the handoff ADDENDUM (review notes …)
- cb583bb docs: rewrite AGENTS.md to stable mechanics only (<60 lines)
- dda5164 docs: add redacted historical session transcript (0153-era)
Branch master; no push requested. Repo clean except the three shim/pra/out015x
dirs and work/census29.py noted above.
