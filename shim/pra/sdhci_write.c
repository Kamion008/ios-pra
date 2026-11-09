/* sdhci_write.c -- write one 512-byte block at lba via the (already initialised)
 * uBLT/Huawei TMMU-style SDHCI at 0xFF390000. Mirror image of probe.c's sdhci_read.
 *
 * SDHCI (T131 / SD-MMC 4.05) register meanings, offsets from SDHCI base:
 *   0x04 BLKSIZE1/LEN  transfer length (512 here)
 *   0x06 BLKCNT        block count (1)
 *   0x08 ARG1/2        starting LBA
 *   0x0C TRANSFER_MODE bit0 = multi-block (0 = single), bit1 = block-count enable,
 *                      bit4 = direction (1 = READ/device-to-host, 0 = WRITE/host-to-device),
 *                      bit7 = DMA.  So 0x02 == single-block WRITE, no DMA (read used 0x12).
 *   0x0E COMMAND       (index<<2) + data-present flag; 0x183A == CMD24 write single
 *                      block, R1 response, data present (read used 0x113A = CMD17).
 *   0x10 STATUS        32-bit R1 (+DLC) MMDC-style status; error bits 0xfdffe008.
 *   0x20 BUFFER_DATA_PORT  (exists only if 0x24 PRESENT_STATE bit16 is set)
 *   0x24 PRESENT_STATE bit16 = data buffer port, bits0/1 = command/data inhibit
 *   0x30 MMC_STATUS    poll bit0 = command complete, bit1 = transfer complete,
 *                      bit4 = VBMR (buffer-write ready, host-to-device), bit5 = DR
 *                      (data ready, read direction); mask 0x7ff checked as busy/error,
 *                      write-1-to-clear to acknowledge, as in read().
 *   0x34 STATUS_EN / 0x38 SIGNAL_EN: save/restore so we leave the device as we found it.
 */

static int sdhci_write(uint64_t lba, const void *in)
{
    uint32_t present = rd32(SDHCI + 0x24);
    if (!(present & (1u<<16))) return -1;
    if (present & 0x3) return -2;

    struct sdhci_state s = { rd16(SDHCI+0x04), rd16(SDHCI+0x06), rd16(SDHCI+0x0C),
                             rd32(SDHCI+0x08), rd32(SDHCI+0x34), rd32(SDHCI+0x38) };

    wr32(SDHCI+0x38, 0); wr32(SDHCI+0x34, 0x7ff); wr32(SDHCI+0x30, 0x7ff);
    wr16(SDHCI+0x04, 512); wr16(SDHCI+0x06, 1);
    wr32(SDHCI+0x08, (uint32_t)lba);
    wr16(SDHCI+0x0C, 0x02);              /* single block, WRITE (dir bit4=0), no DMA */
    __asm__ volatile("dsb sy" ::: "memory");
    wr16(SDHCI+0x0E, 0x183A);            /* CMD24 write single block, R1, data present */

    int rc=-3; uint32_t st=0;
    for (unsigned i=0;i<2000000;i++){ st=rd32(SDHCI+0x30); if(st&0x7ffu){rc=-4;break;} if(st&1u){rc=0;break;} }
    if(rc){ con_printf("[sdhci wr cmd fail %d]\n",rc); goto restore; }
    if(rd32(SDHCI+0x10) & 0xfdffe008u){ rc=-5; con_printf("[sdhci wr r1 err]\n"); goto restore; }
    wr32(SDHCI+0x30, 1u);                /* acknowledge command-complete (bit0) */
    for (unsigned i=0;i<2000000;i++){ st=rd32(SDHCI+0x30); if(st&0x7ffu){rc=-6;break;} if(st&(1u<<4)){rc=0;break;} }
    if(rc){ con_printf("[sdhci wr bwr fail %d]\n",rc); goto restore; }
    { const uint32_t *p = (const uint32_t *)in; for(unsigned i=0;i<128;i++) wr32(SDHCI+0x20, p[i]); }
    for (unsigned i=0;i<2000000;i++){ st=rd32(SDHCI+0x30); if(st&0x7ffu){rc=-7;break;} if(st&(1u<<1)){rc=0;break;} }
    if(rc){ con_printf("[sdhci wr xfer fail %d]\n",rc); goto restore; }
    wr32(SDHCI+0x30, (1u<<1)|(1u<<4));   /* acknowledge transfer-complete (bit1) + BWR (bit4) */
    rc=0;
restore:
    wr16(SDHCI+0x04,s.blksiz); wr16(SDHCI+0x06,s.blkcnt); wr16(SDHCI+0x0C,s.transfer);
    wr32(SDHCI+0x08,s.arg); wr32(SDHCI+0x34,s.status_en); wr32(SDHCI+0x38,s.sig_en);
    return rc;
}
