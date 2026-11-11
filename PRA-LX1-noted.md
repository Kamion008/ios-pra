# PRA-LX1 bring-up notes

Updated 2026-11-11.

## 0138 CI and package

- GitHub Actions run [43082795820](https://github.com/Kamion008/ios-pra/actions/runs/43082795820) completed successfully for commit `103bfb8932f2947929ba4495fffc216c14c65a52`.
- The `xnu-kernel` artifact manifest reports SHA-256 `a821543680cf3665f772854af0866222c88fc519923e6525f24b0424c5f8850e` for the artifact archive.
- Extracted `kernel.development.pra` SHA-256: `909761192f9f45d320c54e1c8306ca90f1508c3045ddd6335df07de764a69408`.
- Packaged `shim/pra/outxnu/pra-xnu.img`: 5,980,160 bytes; SHA-256 `93599fee798eb0b36e68611b894570bc26f827519a5ba47a34bfc1e2c2b6af91`.

These establish CI build success and local packaging only. They do not establish that the image has been flashed or booted on the PRA-LX1.

## Hardware result

- A sandboxed fastboot attempt could not initialize libusb (`-99`). Retrying in elevated `bash` detected exactly one fastboot device.
- Hardware flash: `shim/pra/outxnu/pra-xnu.img` was written to the `kernel` partition; `Sending` and `Writing` both returned `OKAY`. Fastboot printed an AVB-footer warning that the partition size was reported as zero, but the write completed successfully.
- `fastboot reboot` returned `OKAY` after the flash.
- Runtime observation from `PXL_20261111_192201710.jpg`: early network-interface thread scheduling completes; the screen reaches `Waiting on <dict ... IOMedia ... Apple_HFS ...>`, then reports `preemption count not 0 on thread ... (1)`. The original panic string repeats the same message. The photo does not show a successful root-device mount or userspace boot.
- In the flashed image, the reported caller address `0xfffffff007420a1c` lies in the standard `preempt_count_notzero` symbol range (`0xfffffff007420a04` through `0xfffffff007420a48`). Disassembly of `return_to_user` in this kernel shows a direct branch to that panic stub, with no call to `_pra_preempt_notzero`; the kernel also lacks the `PRA-PREEMPT` string. The prior 0137 kernel artifact contains both the call and string. The 0138 buildtree source does contain the 0137 call, so its packaged kernel does not reflect the source shown in that buildtree. Investigate build outputs/rebuild behavior and add a linked-kernel assertion before another hardware flash.

## Later GPU research

- User supplied [Nik300/viva-gpu](https://github.com/Nik300/viva-gpu) as a useful reference for a later GPU investigation.

