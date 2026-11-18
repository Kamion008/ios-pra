# ring45 (boot T4) evidence extract - pulled 2026-11-18 19:43, sha 3151ebe7
# fresh region = [512, ~159232) = 155.0 KiB (159232-512 = 158720 B) (last differing byte vs ring44); each boot writes from sector 1

## the touch ladder (fresh content):
PRA touch: i2c ffd73000 COMP_VERSION=3132302a COMP_TYPE=44570140
PRA touch: irq gpio28.0 dat=0 dir=0 idle=0
PRA touch: rails raw: vbus=00000002 ldo4=00000003 ldo17=00000000
PRA touch: rails on: VDDIO VCI enabled, 20 ms ramp
PRA touch: reset gpio18.1 done dir=2 dat=0
PRA touch: BL_LAUNCH_APP write failed err=6, probe continues
PRA touch: HID desc read failed err=6 (address NACK); irq polling continues
PRA touch: probe done, 10 ms poll worker started
PRA touch: irq lo/hi=1000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1
PRA touch: irq lo/hi=2000/0 idle=0 reports=0 errs=0 corrupt=0 last: slot=-1 x=-1 y=-1 p=-1

## the 0179 gate evidence (fresh content):
first sel 0 (kAKSOpen, opens the 0179 gate): SWEET AKS: keybagd sel 0 arg0 0 in 0/0 out 0/0 -> 0x0
sel 0 count: 92 first at fresh line 306
first sel 17 -> 0x0 at fresh line 780 : SWEET AKS: ReportCrash sel 17 arg0 0 in 1/0 out 0/4096 -> 0x0
sel 17 -> 0x0 count: 440 of 440
sel 9\b at fresh line 1184 : SWEET SURF: backboardd sel 9
sel 12\b at fresh line 1168 : SWEET FB: backboardd sel 12 in 1/0 out 0/0 -> 0x0
sel 5\b at fresh line 1186 : SWEET SURF: backboardd sel 5

## census (fresh region):
lines: 2770
exec xpcproxy: 555
SWEET AKS lines: 724
(boots: T2 fresh 1295 exec/34 min = ~38/min; T3 fresh 521/12 min = ~42/min; T4 fresh 555/47 min = ~12/min; the fresh slice = [512,159232) - the naive [0,159744) slice adds 7 STALE lines from sector 311)
