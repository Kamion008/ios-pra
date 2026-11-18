# The pratouch gate on pra_touch_probe (quoted from the post-0180 buildtree,
#  work/ci181/post0180/xnu/iokit/bsddev/IOKitBSDInit.cpp:799-803):

	//	emmcprobe above. Without pratouch=1 the driver never maps a
	//	window and the boot is unchanged.
	//
	{
		uint32_t pratouch = 0;
		PE_parse_boot_argn("pratouch", &pratouch, sizeof(pratouch));
		if (pratouch == 1) {
			pra_touch_probe();
		}
	}
	if (strcmp(rdBootVar, "sdhcroot0") == 0) {

-> without 'pratouch=1' the probe never runs at all, so a no-pratouch boot
-> cannot discriminate the 0181 bus_on gate (round-8 F); the discriminating
-> boot = pratouch=1 WITHOUT pratouchreset.
