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
#     2022/09/19, Chris.Ke

# Stop if error occurs.
set -e

# Build the project
# sudo make

# Build the BSP file for factory production
# sudo make release_m

# Build the BSP file for factory production
# sudo make release_d

# Build the BSP source for the customer
# sudo make release_s

# Build the BSP SDK for customer
sudo make
sudo make release_o

# Build the BSP Kernel and Device Tree
sudo make
sudo make release_k

# Build the test tool
# sudo make extra

# Create the version folder location for remote file server
sudo make jenkins_u
