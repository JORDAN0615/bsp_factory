url_driver=https://developer.nvidia.com/downloads/embedded/L4T/r38_Release_v4.0/release/Jetson_Linux_R38.4.0_aarch64.tbz2
folder_driver=Linux_for_Tegra
file_driver=sdk.tbz2

url_rootfs=https://developer.nvidia.com/downloads/embedded/L4T/r38_Release_v4.0/release/Tegra_Linux_Sample-Root-Filesystem_R38.4.0_aarch64.tbz2
file_rootfs=rootfs.tbz2

url_source=https://developer.nvidia.com/downloads/embedded/L4T/r38_Release_v4.0/source/public_sources.tbz2
file_source=source.tbz2

path_kernel=Linux_for_Tegra/source
file_kernel=kernel_src.tbz2
path_kernel_source=kernel/kernel-noble
config_file_kernel_oot=kernel_oot_modules_src.tbz2
config_file_kernel_display=nvidia_kernel_display_driver_source.tbz2
config_kernel_setup_type=empty
config_kernel_build_dir=.
config_kernel_headers=/root/build/kernel/kernel/kernel-noble

url_toolchain=https://developer.nvidia.com/downloads/embedded/L4T/r38_Release_v2.0/release/x-tools.tbz2
folder_toolchain=x-tools
file_toolchain=toolchain.xz
toolchain_prefix=aarch64-none-linux-gnu-
config_toolchain_path=aarch64-none-linux-gnu/bin

path_dtb=kernel-devicetree/generic-dts/dtbs
file_dtb=tegra264-p4071-0000+p3834-0008-nv.dtb
flash_platform=jetson-agx-thor-devkit
flash_partition=internal
flash_external_xml=tools/kernel_flash/flash_l4t_t264_nvme.xml
flash_qspi_xml=empty
config_flash_xml=empty
config_kernel_defconfig=defconfig
config_kernel_local_version=-tegra
config_kernel_arch=arm64
config_kernel_build_type=build_jetpack_7_v2
config_kernel_copy_dtb=dtb_all_v2
config_kernel_nv_display=nvgpu/drivers/gpu/nvgpu/nvgpu.ko
config_kernel_install_module=modules_all_jetpack_7_v2

is_build_kernel=1
is_build_dtb=1
is_build_initrd=1
is_add_version=1
is_add_changelog=0
is_build_cbo=0
is_build_nvgpu=1
is_setup=1
is_overwrite_headers=0
is_overwrite_include=0

type_docker_base=1

# For kenrel and drivers
config_file_kernel_config=kernel/kernel/kernel-noble/arch/arm64/configs/defconfig
config_path_lib_module=/usr/lib/modules/6.8.12-tegra/kernel

config_sdk_flash_xml=empty
config_sdk_flash_xml_emmc_node=//partition_layout/device[@type="sdmmc_user"]

# For build flow kernel_dtb
# config_build_kernel_dtb_stop_after_kernel=true
# config_build_kernel_dtb_temp_base=9b0b0271e33d
config_kernel_dtb_is_build_kernel_modules=true
config_kernel_dtb_is_build_kernel_header=false
config_kernel_dtb_is_build_kernel_include=false

# For gpio command.
config_gpio_res_pinmux=orin/pinmux_*.csv
config_gpio_res_pinconf=orin/pinconf_pin_*.log
config_gpio_res_range=orin/gpio_range_*.log

config_gpio_line_pattern_head=^
config_gpio_line_pattern_tail=,

config_gpio_field_gpio_id=6
config_gpio_field_signal_name=2

config_gpio_field_func_gpio_0_name=6
config_gpio_field_func_sfio_0_name=7
config_gpio_field_func_sfio_1_name=8
config_gpio_field_func_sfio_2_name=9
config_gpio_field_func_sfio_3_name=10

config_gpio_field_func_gpio_0_val=20
config_gpio_field_func_sfio_0_val=16
config_gpio_field_func_sfio_1_val=17
config_gpio_field_func_sfio_2_val=18
config_gpio_field_func_sfio_3_val=19

som_board_id=3701
som_board_sku=0004
som_board_fab=500
som_board_rev=H.0
som_fuse_level=fuselevel_production

bsp_board=MIC-741
bsp_som=Thor
bsp_jetpack=7.1
bsp_jetpack_step=
bsp_version=V1.0.1
bsp_version_path=/opt

pchain_git=git@172.17.4.45:isystem-esg-linux-bsp/patch_package_list.git

framework_git=git@172.17.4.45:isystem-esg-linux-bsp/framework_ria.git
framework_branch=master
framework_commit=33c32d52
