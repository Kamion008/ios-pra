/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef PRA_SDHCI_H
#define PRA_SDHCI_H

#include <stdint.h>

/* Read one 512-byte block with the polled PIO path the diagnostic shim
 * proved on this phone. Read-only: CMD17, no writes, no DMA, no interrupts.
 * Returns 0 on success, negative on error. */
int pra_sdhci_read(uint64_t lba, void *out);

#endif
