# EVIDENCE 1 — pra_sdhci.c lock sites (primary excerpts)

Provenance: extracted from CI run 44119547672 artifact xnu-buildtree/buildtree.tgz
(the source tree that CI actually compiled for the 0175-era kernel; markers
'CMD18+CMD23 multi-block enabled' and 'PRA LOG: strat flush' verified present,
grep -c = 1 each). Path: xnu/bsd/dev/pra_sdhci.c (2647 lines).
Line numbers are the buildtree file's own.

## The mutex (line 287)

    287: static LCK_MTX_DECLARE(pra_emmc_lock, &pra_emmc_grp);

## pra_log_write_sector — the periodic flusher's write path (1071-1093)

 1071	 * lock is per sector: a 4 MiB flush must not stall filesystem I/O. */
 1072	static int
 1073	pra_log_write_sector(uint32_t lba, const uint8_t *sector)
 1074	{
 1075		int error;
 1076		if (!pra_log_erecovery_sectors ||
 1077		    lba < pra_log_erecovery_lba ||
 1078		    (uint64_t)lba - pra_log_erecovery_lba >= PRA_LOG_SECTORS) {
 1079			return EROFS;
 1080		}
 1081		/* try_lock, not lock (0003): a strat request holds pra_emmc_lock for
 1082		 * its whole sector loop, which during a wedge or a storm is seconds
 1083		 * or minutes of queueing per 512-byte sector. Blocking here is how a
 1084		 * wedged strat starved the flusher: ring21 came back byte-identical
 1085		 * to ring20. Skip this sector now; the EBUSY handling in the flush
 1086		 * loop keeps the flush position and the next 10 s tick retries. */
 1087		if (!lck_mtx_try_lock(&pra_emmc_lock)) {
 1088			return EBUSY;
 1089		}
 1090		error = pra_emmc_write_raw(lba, sector);
 1091		lck_mtx_unlock(&pra_emmc_lock);
 1092		return error;
 1093	}

## pra_log_append — the RAM ring, lock-free (1095-1107)

 1095	/* _cnputc may execute in any context. Keep this path free of locks and I/O. */
 1096	void pra_log_append(const char *c, int size);
 1097	void
 1098	pra_log_append(const char *c, int size)
 1099	{
 1100		if (!pra_log_enabled || size <= 0) {
 1101			return;
 1102		}
 1103		uint64_t at = os_atomic_add_orig(&pra_log_total, (uint64_t)size, relaxed);
 1104		for (int i = 0; i < size; i++) {
 1105			pra_log_ring[(at + (uint64_t)i) % PRA_LOG_SIZE] = c[i];
 1106		}
 1107	}

## pra_log_halt — the flusher can halt forever (1109-1116)

 1109	static void
 1110	pra_log_halt(void)
 1111	{
 1112		printf("PRA LOG: halted; power off and reflash to continue\n");
 1113		for (;;) {
 1114			__asm__ volatile("wfe");
 1115		}
 1116	}

## The periodic flusher thread (1187-1256)

 1191	static uint64_t pra_log_seq;
 1193	static void
 1194	pra_log_thread(__unused void *arg, __unused wait_result_t wr)
 1195	{
 1196		uint64_t flushed = 0, last_total = 0;
 1197		int idle = 0, ticks = 0, write_fails = 0;
 1198		uint8_t sector[512];
 1199
 1200		for (;;) {
 1201			(void)tsleep(&pra_log_chan, PZERO, "pralog", hz * 10);
 1202			ticks++;
 1203			uint64_t total = os_atomic_load(&pra_log_total, relaxed);
 1204			if (total != flushed) {
 1205				/* A full ring means only the newest PRA_LOG_SIZE bytes
 1206				 * still matter; skip whatever was overwritten. */
 1207				uint64_t pos = total - flushed >= PRA_LOG_SIZE ?
 1208				    total - PRA_LOG_SIZE : flushed;
 1209				int error = 0;
 1210				while (pos < total && !error) {
 1211					uint32_t block =
 1212					    (uint32_t)((pos % PRA_LOG_SIZE) / 512u);
 1213					uint64_t lba = pra_log_erecovery_lba + 1u + block;
 1214					if (lba >= pra_log_erecovery_lba +
 1215					    PRA_LOG_SECTORS || lba > UINT32_MAX) {
 1216						error = EINVAL;
 1217						break;
 1218					}
 1219					memcpy(sector,
 1220					    pra_log_ring + (size_t)block * 512u,
 1221					    sizeof(sector));
 1222					error = pra_log_write_sector((uint32_t)lba,
 1223					    sector);
 1224					pos += 512u - (pos & 511u);
 1225				}
 1226				if (!error) {
 1227					struct pra_log_header h = {
 1228						.magic = { 'P', 'R', 'A', 'L', 'O', 'G',
 1229							   '1', '\0' },
 1230						.version = 1,
 1231						.size = PRA_LOG_SIZE,
 1232						.total = total,
 1233						.seq = ++pra_log_seq,
 1234					};
 1235					memset(sector, 0, sizeof(sector));
 1236					memcpy(sector, &h, sizeof(h));
 1237					error = pra_log_write_sector(
 1238					    (uint32_t)pra_log_erecovery_lba, sector);
 1239				}
 1240				if (error) {
 1241					/* The root is mounted writable, so a filesystem write
 1242					 * may own the SDHCI channel while this flush runs: EBUSY
 1243					 * is expected and transient. Keep flushed where it is so
 1244					 * the next tick rewrites the same blocks, and bound how
 1245					 * many complaints reach the console: a stuck flusher must
 1246					 * never end the log loop, or the idle and at-limit dumps,
 1247					 * which are what makes a hang readable at all. */
 1248					if (++write_fails <= 8 || write_fails % 64 == 0) {
 1249						printf("PRA LOG: write failed %d after %d ticks\n",
 1250						    error, write_fails);
 1251					}
 1252				} else {
 1253					write_fails = 0;
 1254					flushed = total;
 1255				}
 1256			}
(1257-1271: idle_limit / at_limit checks call pra_log_memory_tail() then
 pra_log_halt() — the halt loops forever on wfe; limits parsed at 1503-1504,
 0 disables each.)

## pra_log_flush_locked — core the panic flush ran inline (1328-1369, excerpt)

 1329	 * pra_emmc_lock must be HELD: this is the core the panic
 1330	 * flush ran inline, refactored out so strat can call it from the CMD18
 1331	 * chunk-failure path (strat already holds the lock) and the panic path can
 1332	 * call it after acquiring-or-stealing the lock.

## pra_log_strat_flush — called with pra_emmc_lock HELD (1371-1420, excerpt)

 1371	/* strat-side evidence flush, called with pra_emmc_lock held whenever a CMD18
 1372	 * chunk fails and again when the 2-strike latch fires (force): a wedged
 1373	 * strat previously starved the periodic flusher and the ring came back
 1374	 * byte-identical to the previous boot (ring20/ring21), so the flush has to
 1375	 * happen where the wedge is. Writes the newest 128 ring blocks (64 KiB -
 1376	 * every chunk-failure, recover and busy-skip line lands in the tail) plus
 1377	 * the header: bounded work on a healthy card (~0.2 s at the measured ~600
 1378	 * KiB/s write rate) and one bounded EBUSY on a wedged one. Rate-limited to
 1379	 * one per 10 s - a recurring failure mode must not turn the flush itself
 1380	 * into the flood - with the suppressed count carried on the next line. The
 1381	 * latch flush bypasses the limit: it happens at most once per boot and is
 1382	 * the terminal event. */
 1408		if (!force && pra_log_strat_flush_at &&
 1409		    now - pra_log_strat_flush_at < 10ULL * 1920000ULL) {
 1410			pra_log_strat_flush_skipped++;
 1411			return;
 1412		}

## pra_log_panic_flush — the steal (1429-1483, excerpts)

 1422	/* The flusher thread dies with the boot, so a panic loses everything printed
 1424	 * since its last 10 s tick - the pe_init.c:314 panic (0153) left no trace in
 1425	 * the ring for exactly this reason. Called once from the panic path, after
 1426	 * the paniclog is printed. ... The eMMC lock is waited for, then stolen
 1427	 * (see below); a racy disk copy is acceptable, the screen backtrace is the
 1442	 * ... 0158's ~1 ms spin loop (100 x 10000) lost exactly the boot it was
 1443	 * built for, so wait up to 5 s, one delay(1000) per try; delay() is the
 1444	 * busy-wait interval from kern/clock.c and is safe on the panic path.
 1446	 * If the lock is still held after that, steal it: a parked CPU that
 1447	 * held the lock will never release, and a flusher stalled mid-write
 1448	 * on a live CPU has had 5 s - far longer than a normal tick. The bsd
 1449	 * view of lck_mtx_t is opaque ({uintptr_t opaque[2]}); the MACH view
 1450	 * is tsid:type, grp, then the 64-bit state word, so opaque[1] is the
 1451	 * state in either layout. Zeroing just that word clears owner,
 1452	 * ilocked and the wait queues while keeping the group pointer valid
 1453	 * for try_lock/unlock. We are panicking: a holder that ever wakes
 1454	 * will find the mutex moved under it, but the kernel halts after the
 1455	 * flush and the printf backtrace above is the capture that counts.
 1456	 */
 1457		unsigned ms = 0;
 1458		while (!lck_mtx_try_lock(&pra_emmc_lock)) {
 1459			if (ms >= 5000u) {
 1460				printf("PRA LOG: panic flush: lock stuck, stealing\n");
 1461				((volatile uintptr_t *)(void *)&pra_emmc_lock)[1] = 0;
 1462				if (!lck_mtx_try_lock(&pra_emmc_lock)) {
 1463					printf("PRA LOG: panic flush: steal failed, "
 1464					    "skipping\n");
 1465					return;
 1466				}
 1467				break;
 1468			}
 1469			ms++;
 1470			delay(1000);
 1471		}
 1472		total = os_atomic_load(&pra_log_total, relaxed);
(1473-1478: used clamped to PRA_LOG_SIZE; pra_log_flush_locked(0, used/512, total, 0))
 1479		lck_mtx_unlock(&pra_emmc_lock);
 1480		if (error) {
 1481			printf("PRA LOG: panic flush failed %d\n", error);
 1482		}
 1483	}

## strat — the request loop holds the lock across ALL sectors (2378-2508, core)

 2378		bool is_read = (buf_flags(bp) & B_READ) != 0;
 2379		uint32_t cmds = 0;
 2380		uint64_t t0 = pra_emmc_stats ? mach_absolute_time() : 0;
 2381		lck_mtx_lock(&pra_emmc_lock);
 2382		for (uint32_t n = 0; n < count;) {
 2383			uint64_t pos = off + n;
 2384			uint32_t skip = pos & 511u;
 2385			uint32_t take = MIN(count - n, 512u - skip);
 2386			uint32_t lba = (uint32_t)(pra_emmc_first_lba + pos / 512u);
(2396-2482: CMD18 multi-block chunk path — pra_emmc_read_multi(...) for up
 to PRA_MULTI_MAX sectors into the SHARED pra_emmc_multi_buf, then memcpy to
 the request buffer; on chunk failure: pra_emmc_recover() + the strat flush
 calls at 2423/2468/2473 — all with the lock held)
 2483			if (is_read) {
 2484				error = pra_emmc_read_sector(lba, pra_emmc_bounce);
 2485				cmds++;
 2486				if (!error) {
 2487					memcpy(vaddr + n, pra_emmc_bounce + skip, take);
 2488				}
 2489			} else {
 2490				if (skip || take != 512u) {
 2491					error = pra_emmc_read_sector(lba, pra_emmc_bounce);
 2492					cmds++;
 2493				}
 2494				if (!error) {
 2495					memcpy(pra_emmc_bounce + skip, vaddr + n, take);
 2496					error = pra_emmc_write_sector(lba, pra_emmc_bounce);
 2497					cmds++;
 2498				}
 2499			}
 2500			if (error) {
 2501				break;
 2502			}
 2503			n += take;
 2504			buf_setresid(bp, count - n);
 2505		}
 2506		lck_mtx_unlock(&pra_emmc_lock);
 2507		buf_unmap(bp);
 2508		pra_emmc_note_io(count - buf_resid(bp), cmds, t0, is_read);

Note: pra_emmc_bounce and pra_emmc_multi_buf are shared statics; between
2381 and 2506 there are no returns or gotos (only break/continue), so the
lock/unlock pair is balanced on every path through the loop.

## flusher thread spawn (1503-1510)

 1503		pra_log_idle_limit = idle > 0 ? (idle + 9) / 10 : 0;
 1504		pra_log_at_limit = at > 0 ? (at + 9) / 10 : 0;
 1507		    pra_log_erecovery_lba, PRA_LOG_SECTORS, pra_log_idle_limit * 10,
 1508		    pra_log_at_limit * 10);
 1510		if (kernel_thread_start(pra_log_thread, NULL, &thread) == KERN_SUCCESS) {
