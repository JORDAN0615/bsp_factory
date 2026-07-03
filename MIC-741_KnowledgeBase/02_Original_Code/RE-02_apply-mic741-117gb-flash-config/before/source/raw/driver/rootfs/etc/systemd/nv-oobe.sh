#!/bin/bash

# SPDX-FileCopyrightText: Copyright (c) 2024-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

function display_is_plugged() {
	grep -q "^connected$" /sys/class/drm/*/status
}

function start_graphical_target() {
	/bin/systemctl set-default graphical.target || true
	/bin/systemctl --no-block start graphical.target || true
}

function start_oem_config_headless() {
	CONF_FILE="/etc/nv-oem-config.conf"
	UART_PORT="$(grep uart-port "${CONF_FILE}" | cut -d '=' -f 2)"
	if [[ -n "${UART_PORT}" ]]; then
		for i in {1..5}; do
			if [[ -e "/dev/${UART_PORT}" ]]; then
				break;
			elif [[ "${i}" =~ "5" ]]; then
				if [[ -e "/dev/ttyTCU0" ]]; then
					UART_PORT="ttyTCU0"
				elif [[ -e "/dev/ttyAMA0" ]]; then
					UART_PORT="ttyAMA0"
				elif [[ -e "/dev/ttyAMA6" ]]; then
					UART_PORT="ttyAMA6"
				elif [[ -e "/dev/ttyUTC0" ]]; then
					UART_PORT="ttyUTC0"
				elif [[ -e "/dev/ttyS0" ]]; then
					UART_PORT="ttyS0"
				else
					UART_PORT=""
				fi
			else
				sleep 1
			fi
		done
	fi

	if [[ -n "${UART_PORT}" ]]; then
		/bin/stty -F /dev/${UART_PORT} 115200 cs8 -parenb -cstopb

		msg="<5>Please complete NVIDIA OOBE on the serial port "
		msg+="provided by Jetson's USB device mode connection. e.g. "
		if [[ "${UART_PORT}" =~ "ttyGS0" ]]; then
			msg+="/dev/ttyACMx "
		else
			msg+="/dev/ttyUSBx "
		fi
		msg+="where x can 0, 1, 2 etc."
		/bin/echo "${msg}" > "/dev/kmsg"

		/bin/systemctl start nv-oem-config-debconf@${UART_PORT}.service
	else
		/bin/echo "<5>NVIDIA OOBE could not find serial port to configure system!" > "/dev/kmsg"
		exit 1
	fi
}

# Check whether the pre-seed mode is enabled
KERNEL_CMDLINE="$(cat /proc/cmdline)"

if [ -e "/etc/cloud/cloud.cfg.d/99-nv-preseed.cfg" ]; then
	if [[ "${KERNEL_CMDLINE}" =~ "nv-auto-config" ]]; then
		/bin/echo "<5>NVIDIA OOBE will auto setup by cloud-init service..." > "/dev/kmsg"
		start_graphical_target
		exit 0
	else
		rm -rf "/etc/cloud/cloud.cfg.d/99-nv-preseed.cfg"
	fi
fi

if display_is_plugged; then
	/bin/echo "<5>NVIDIA OOBE will launch Gnome Initial Setup application..." > "/dev/kmsg"
	start_graphical_target
else
	start_oem_config_headless
fi

exit 0
