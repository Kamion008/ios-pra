# The 0182 arithmetic, computed by script (the AGENTS.md standing rule);
# every number the claim cites is reproduced here with its tool output.
# dtsi inputs: hi6250_udp_default_pin.dtsi gpio187_pmx_func = <0x024 0x1>,
# gpio188_pmx_func = <0x028 0x1> (:714-725), gpio187_cfg_func = <0x02C 0>,
# gpio188_cfg_func = <0x030 0> (:2477-2480, :2492-2495);
# live/iomem.txt:92-93 = fff11000-fff110ab, fff11800-fff118bb.

gpio187 mux offset  (187-178)*4                                = 36 (0x24)
gpio188 mux offset  (188-178)*4                                = 40 (0x28)
gpio187 cfg offset  (187-176)*4                                = 44 (0x2c)
gpio188 cfg offset  (188-176)*4                                = 48 (0x30)
gpio222 mux offset  (222-178)*4 -- formula only                = 176 (0xb0)
gpio222 mux offset  -- the dtsi ACTUAL (:931-933)              = 0x0a8; delta 8 = 2
   packed slots before it (the absent gpio191 + one more); 0x0a8+4 = 0xac
   = the window end (iomem:92) - the window size CONFIRMS the last entry
gpio192 mux offset  (192-178)*4 -- the dtsi says 0x034, so the bank is PACKED = 56 (0x38)
gpio012 mux offset  (12-3)*4   -- pmx0's bank base = 3         = 36 (0x24)
PMX1 window bytes   0xab+1                                     = 172 (0xac)
PMX1 window registers (0xab+1)//4                              = 43 (0x2b)
PMX3 window bytes   0xbb+1                                     = 188 (0xbc)
PMX3 window registers (0xbb+1)//4                              = 47 (0x2f)
CON 0x63 as the setup's fields 0x01|0x02|0x20|0x40             = 99 (0x63)
cfg reachability from the single PMX1 map:
0xFFF11000 + 0x82C = 0xfff1182c  (gpio187 cfg = the pinmux@fff11800
                                     window's 0x02C)
0xFFF11000 + 0x830 = 0xfff11830  (gpio188 cfg = the window's 0x030)
bl flush  (0x0c000001 & 0xff800000) >> 23                      = 24 (0x18)
desc flush (0x01000001 & 0xff800000) >> 23                     = 2 (0x2)
BL frame commands 2 reg + 11 payload                           = 13 (0xd)
T5 fresh slice length (168959+1)-512 = 168448 B -> //1024    = 164 (0xa4)

NOTE the two anomalies the script surfaces (recorded, not hidden):
- gpio192: the formula gives 0x38 but the dtsi says 0x034 -> the pmx1
  bank is PACKED (the absent gpio191); the per-entry dtsi values are
  the authority, not the formula.
- bl flush = 24 for 13 queued commands (desc = 2 for 2 = consistent):
  TX_FLUSH_CNT's units on v1.20* are uncalibrated; bit 0 (ADDR7_NACK)
  is the only decode the verdict relies on.
