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
#     2024/03/09, Chris.Ke

set -e

# Common
common_apt_get_update_v1
common_install_pps_tool
common_install_devmem2
common_install_v4l_utils
common_install_python3_libgpiod
common_install_socat
common_install_linuxptp
common_install_nvme_cli
common_install_byobu
