check_audio () {
	while true
	do
		sleep 0.5
		ls /sys/kernel/debug/asoc/*/*/dapm/CVB-RT*OUT*MIXL 2>/dev/null || continue
		ls /sys/kernel/debug/asoc/*/*/dapm/CVB-RT*DAC*MIXR 2>/dev/null || continue
		ls /sys/kernel/debug/asoc/*/*/dapm/CVB-RT*Stereo*DAC*MIXL 2>/dev/null || continue
		ls /sys/kernel/debug/asoc/*/*/dapm/CVB-RT*Stereo*DAC*MIXR 2>/dev/null || continue
		ls /sys/kernel/debug/asoc/*/*/dapm/CVB-RT*OUT*MIXL 2>/dev/null || continue
		ls /sys/kernel/debug/asoc/*/*/dapm/CVB-RT*OUT*MIXR 2>/dev/null || continue
		ls /sys/kernel/debug/asoc/*/*/dapm/CVB-RT*LOUT*MIX 2>/dev/null || continue
		break
	done
}

enable_audio () {
	check_audio
	amixer cset name="CVB-RT DAI select" "1:1|2:2"
	amixer cset name="CVB-RT DAC MIXL INF1 Switch" 1
	amixer cset name="CVB-RT DAC MIXR INF1 Switch" 1
	amixer cset name="CVB-RT Stereo DAC MIXL DAC L1 Switch" 1
	amixer cset name="CVB-RT Stereo DAC MIXR DAC R1 Switch" 1
	amixer cset name="CVB-RT OUT MIXL DAC L1 Switch" 1
	amixer cset name="CVB-RT OUT MIXR DAC R1 Switch" 1
	amixer cset name="CVB-RT LOUT MIX OUTVOL L Switch" 1
	amixer cset name="CVB-RT LOUT MIX OUTVOL R Switch" 1
	amixer cset name="CVB-RT OUT Channel Switch" 1
	amixer cset name="CVB-RT OUT Playback Switch" 1
	amixer cset name="ADMAIF1 Mux" "I2S4"
	amixer cset name='I2S4 Mux' 'ADMAIF1'
}

init_pinmux_gpio () {
	# U257_DIR, GPIO65, J7, GPIO3_PZ.07, Pull High, Output, Function GPIO
	busybox devmem 0x810c28b070 w 0x09
	# U257_DIR, GPIO65, J7, GPIO3_PZ.07, Direction GPIO -> SoM
	sudo gpioset $(sudo gpiofind PZ.07)=0

	# U372_DIR, GPIO49, G6, GPIO3_PAL.00, Pull High, Output, Function GPIO
	busybox devmem 0x810c28b068 w 0x09
	# U372_DIR, GPIO49, G6, GPIO3_PAL.00, Direction GPIO -> SoM
	sudo gpioset $(sudo gpiofind PAL.00)=0
	
	# U257_B1, GPIO04, B59, GPIO3_PP.04, Pull None, Input, Function GPIO
	busybox devmem 0x810c286010 w 0x51
	# U372_B1, GPIO05, A59, GPIO3_PP.03, Pull None, Input, Function GPIO
	busybox devmem 0x810c286018 w 0x51
}

start () {
	enable_audio
	init_pinmux_gpio
}

$1 "${@:2}"
