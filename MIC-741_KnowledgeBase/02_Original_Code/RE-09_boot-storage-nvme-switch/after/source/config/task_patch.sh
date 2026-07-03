#!/bin/bash
#
# Copyright (C) 2016 Advantech Co., Ltd. - http://www.advantech.com.tw/
# All Rights Reserved.
#
# NOTICE:  All information contained herein is, and remains the property of
#     Advantech Co., Ltd. and its suppliers, if any.  The intellectual and
#     technical concepts contained herein are proprietary to Advantech Co., Ltd.
#     and its suppliers and may be covered by U.S. and Foreign Patents,
#     patents in process, and are protected by trade secret or copyright law.
#     Dissemination of this information or reproduction of this material
#     is strictly forbidden unless prior written permission is obtained
#     from Advantech Co., Ltd.
#
#     2022/12/21, Chris.Ke

set -e
common_compile_dtb_v1 work driver/bootloader/generic/tegra264-bpmp-3834-0008-4071-xxxx.dts
common_compile_dtbo_v1 work driver/kernel/dtb/L4TConfiguration.dts
common_unzstd_v1 work usr/lib/firmware/rtw88/rtw8822c_fw.bin.zst
common_unzstd_v1 work usr/lib/firmware/rtw88/rtw8822c_wow_fw.bin.zst
common_unzstd_v1 work usr/lib/firmware/rtw89/rtw8852b_fw.bin.zst
common_unzstd_v1 work usr/lib/firmware/rtw89/rtw8852b_fw-1.bin.zst
common_unzstd_v1 work usr/lib/firmware/iwlwifi-ty-a0-gf-a0-86.ucode.zst
common_unzstd_v1 work usr/lib/firmware/iwlwifi-ty-a0-gf-a0.pnvm.zst
common_unzstd_v1 work usr/lib/firmware/intel/ibt-0041-0041.sfi.zst
common_unzstd_v1 work usr/lib/firmware/rtl_bt/rtl8852bu_fw.bin.zst
jetpack_7.0_l4t_update_initrd_v1
jetpack_7.0_extlinux_fdt_v1
jetpack_7.0_copy_dtbo_to_rootfs_v1
jetpack_7.0_l4t_create_default_user_v1 'mic-741' 'mic-741' 'ubuntu' '--advantech-flag'
jetpack_7.0_create_adv_dev_check_v1
jetpack_7.0_create_adv_env_check_v1
jetpack_7.0_create_adv_no_flash_v2
jetpack_7.0_create_adv_only_flash_v2
jetpack_7.0_create_adv_qspi_only_v1
jetpack_7.0_create_adv_flash_v1
jetpack_7.0_create_adv_qspi_v1
jetpack_7.0_create_adv_boot_storage_v2
jetpack_7.0_tool_enable_usb2_0_host_mode_v1 work
