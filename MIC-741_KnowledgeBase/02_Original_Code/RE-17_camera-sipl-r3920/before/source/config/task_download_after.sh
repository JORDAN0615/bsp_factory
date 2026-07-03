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
#     2025/09/03, Chris.Ke

set -e

# ==========================================
TARGET_L4T_VERSION="38.4.0"
# ==========================================

case "$TARGET_L4T_VERSION" in
    "38.4.0")
        URL_SIPL="https://developer.nvidia.com/downloads/embedded/L4T/r38_Release_v4.0/release/Jetson_SIPL_API_R38.4.0_aarch64.tbz2"
        MD5_SIPL="0e7a433679da2bdb5a2ec034c2f3bc6c"
        ;;
    "38.2.1")
        URL_SIPL="https://developer.nvidia.com/downloads/embedded/L4T/r38_Release_v2.1/release/Jetson_SIPL_API_R38.2.1_aarch64.tbz2"
        MD5_SIPL="b8c50af79a38be8fe98b9c7563763309"
        ;;
    *)
        echo "[ERROR] Unsupported L4T Version: $TARGET_L4T_VERSION"
        echo "[ERROR] Please add URL and MD5 for this version in task_download_after.sh"
        exit 1
        ;;
esac

jetpack_7_download_camera_sipl "$TARGET_L4T_VERSION" "$URL_SIPL" "$MD5_SIPL"
