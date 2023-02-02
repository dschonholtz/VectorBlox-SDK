# Notes about this fork.
This is a fork for the Northeastern Wines Lab: https://ece.northeastern.edu/wineslab/

It is designed to enable using the polarFire board, libero and generate hex files for microchip's libero software with ubuntu 22.04 and 1d Convolutional neural networks.

- Converts a conv-1d model into the conv-2d model format that the polarfire software expects. This allows us to run the optimization software on the given h5 tensorflow model.

- We are currently working on supporting inference of models.


# Prerequisites

 Ubuntu 16.04 / 18.04 / 20.04 /22.04 are supported
 If using WSL, ensure you are running from your home directory or have permissions set

# Downloading the SDK

There are two options for downloading the sdk:

 1) Download an archive.  
  Download the zip or tar.gz from https://github.com/Microchip-Vectorblox/VectorBlox-SDK/releases
     
 2) Git clone  
    In order to clone it is necessary to have [git-lfs](https://git-lfs.github.com/) installed.To install git-lfs run the following commands on ubuntu:
    ```
    curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | sudo bash
    apt update && apt install git-lfs
    git lfs install
    ```
     
## Install required dependencies (requires sudo permission)

```
bash install_dependencies.sh
```

## Activate (and installs if needed) Python virtual environment, and sets necessary environment variables
```
source setup_vars.sh
```
If during `source setup_vars.sh` you get an error about "No module named 'mxnet'"
chances are git-lfs is not configured correctly.

# Run tutorials

Several tutorials are provide to generate CoreVectoBlox compatible Binary Large OBjects (BLOBs)

The tutorials download the networks, convert and optimize the network into openvino xml, and
then finally convert the xml into a quantized Vectoblox BLOB with a .vnnx and .hex file extension.

To run the tutorials, follow the below steps. 

```
cd tutorials/{framework}/{network}
bash {network}.sh
```

A list of tutorials can be found [here](./tutorials/README.md)


