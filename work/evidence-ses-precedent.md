# The clock-gated-host precedent (quoted from PRA-LX1-noted.md, the
#  lines the I2C research cites as :1609-1611):

  IOKit drivers registered (AKS/WDT/SURF/HID/PRA charger), then panicked.
- Panic 2 (photo `PXL_20261113_163751479.jpg`): `Kernel data abort, pc
  0xffffff80074936b0 = _pra_charger_status+0xa30` (runtime = link -
  0x7000000000), caller `_sleh_synchronous_sp1`, ESR `0x96000210` (SES, read),
  `far 0xfffffffa863290f8`. `x19 = _pra_i2c + 0x38` = host 1 (`0xFDF0D000`):
  `pra_map_hosts` mapped it and the first `COMP_VERSION` load external-aborted.
  On the hi6250 a clock-gated controller busses errors (SES); it does not read
  as 0/0xFFFFFFFF as the driver assumed. Host 0 answered:
  `COMP_VERSION=3132302a COMP_TYPE=44570140` (genuine DesignWare ID).
- Fixes (patches verified to apply with `patch -p1` against the pre-state):
  - `0152` amended: second host probed only with `prai2c2=1` (default off);

-> a gated-out hi6250 DW host reads as a synchronous external abort, not
-> data - so a live COMP_VERSION/COMP_TYPE readout at diag time proves the
-> window still answers (the CRG-gate case; the IOMCU-reset read behavior
-> is UNKNOWN per research sec 8).
