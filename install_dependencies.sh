#!/bin/bash
# Copyright (C) 2021 Microchip Technologies


# install dependencies
if grep -iEq "ubuntu (16|18|20|22).04" /etc/issue
then
    # Ubuntu
    sudo apt update
  	sudo DEBIAN_FRONTEND=noninteractive apt-get install -y libopenblas-base \
         git \
         libsm6 \
         libxrender1 \
	 libgl1 \
         curl \
         wget \
         unzip \
         python3-enchant \
         python3-venv \
         python3-dev \
         libjpeg-dev \
         build-essential   
    if grep -iEq "ubuntu 20.04" /etc/issue
    then
        #on 20.04 a few more packages are needed to build some pip wheels
        sudo apt-get install -y cmake protobuf-compiler libenchant-dev libjpeg-dev
    fi
    if grep -iEq "ubuntu 22.04" /etc/issue
    then
        # add the deadsnakes ppa for python3.8
        sudo add-apt-repository ppa:deadsnakes/ppa
        sudo apt update
        # install python3.8 with virtual env capabilities and pip
        sudo apt install -y python3.8 python3.8-venv python3.8-dev python3.8-distutils
        #on 22.04 a few more packages are needed to build some pip wheels
        sudo apt-get install -y cmake protobuf-compiler libenchant-2-dev libjpeg-dev
    fi
else
    echo "Unknown OS, please install dependencies manually" && exit 1
fi
