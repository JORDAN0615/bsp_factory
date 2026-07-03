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

# Select the SoM (passed from the Jenkins job as env var bsp_som; default T5000).
# Passed as a make command-line argument so it survives the nested sudo make.
SOM="${bsp_som:-T5000}"

# Build the BSP SDK for customer
sudo make bsp_som=$SOM
sudo make release_o bsp_som=$SOM

# Build the BSP Kernel and Device Tree
sudo make bsp_som=$SOM
sudo make release_k bsp_som=$SOM

# Build the test tool
# sudo make extra bsp_som=$SOM

# Create the version folder location for remote file server
sudo make jenkins_u bsp_som=$SOM
