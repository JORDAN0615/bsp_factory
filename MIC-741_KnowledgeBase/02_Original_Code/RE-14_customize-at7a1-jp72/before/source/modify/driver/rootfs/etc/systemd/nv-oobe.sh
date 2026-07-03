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
		msg="<5>Please complete NVIDIA OOBE on the serial port "
		msg+="provided by Jetson's USB device mode connection. e.g. "
		if [[ "${UART_PORT}" =~ "ttyGS0" ]]; then
			msg+="/dev/ttyACMx "
		else
			msg+="/dev/ttyUSBx "
		fi
		msg+="where x can 0, 1, 2 etc."
		/bin/echo "${msg}" > "/dev/kmsg"

		if [[ "${UART_PORT}" =~ "ttyGS0" ]]; then
			# Set TTY as canonical mode
			stty -F "/dev/${UART_PORT}" icrnl -echo

			# Clear unused data when USB gadget starts
			timeout 0.2 cat "/dev/${UART_PORT}" > /dev/null 2>&1

			# Wait for users launch serial tool and press ENTER key
			while true; do
				timeout 0.1 printf "\rPress ENTER to start System Configuration... " \
					> "/dev/${UART_PORT}"
				if IFS= read -r -t 1 line < "/dev/${UART_PORT}"; then
					[ -z "${line}" ] && break
				fi
			done
		fi

		# Set TTY as interactive mode
		stty -F "/dev/${UART_PORT}" sane

		# Start OEM-config-debconf service
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

# Default user has been created, just init the system directly
adv_log () { echo "$1" | tee /dev/ttyUTC0 /dev/kmsg; }

adv_log "[ADV] Init BSP: Updating Kernel modules config"
depmod -a

adv_log "[ADV] Init BSP: Updating schemas"
glib-compile-schemas /usr/share/glib-2.0/schemas

adv_log "[ADV] Init BSP: Resizing root partition to max size"
dev_part=$(findmnt -T / -o SOURCE -n)
dev_root=$(lsblk -npo pkname $dev_part)
val_part=$(lsblk -pl | grep "$dev_root[^ ]" | grep -n "$dev_part " | cut -d ":" -f 1)
adv_log "[ADV] - Root Device $dev_root"
adv_log "[ADV] - Partition Device $dev_part"
adv_log "[ADV] - Partition Index $val_part"
parted $dev_root print
parted -s $dev_root resizepart $val_part 100%
echo -e "yes\n100%" | parted $dev_root ---pretend-input-tty unit % resizepart $val_part
resize2fs $dev_part
sync

adv_log "[ADV] Init BSP: Done"
start_graphical_target
exit 0

if display_is_plugged; then
	/bin/echo "<5>NVIDIA OOBE will launch Gnome Initial Setup application..." > "/dev/kmsg"
	start_graphical_target
else
	start_oem_config_headless
fi

exit 0
