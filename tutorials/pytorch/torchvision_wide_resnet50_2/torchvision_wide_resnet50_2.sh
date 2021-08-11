
#######################################
#                                     #
#  ____    ____  ______   ___   ___   #
#  \   \  /   / |   _  \  \  \ /  /   #
#   \   \/   /  |  |_)  |  \  V  /    #
#    \      /   |   _  <    >   <     #
#     \    /    |  |_)  |  /  ^  \    #
#      \__/     |______/  /__/ \__\   #
#                                     #
# Refer to Programmer's Guide         #
# for full details                    #
#                                     #
#                                     #
#######################################

set -e
echo "Checking and Activating VBX Python Environment..."
if [ -z $VBX_SDK ]; then
    echo "\$VBX_SDK not set. Please run 'source setup_vars.sh' from the SDK's root folder" && exit 1
fi
source $VBX_SDK/vbx_env/bin/activate

echo "Downloading torchvision_wide_resnet50_2..."
python ../../torchvision_to_onnx.py wide_resnet50_2

echo "Running Model Optimizer..."
# model details @ https://pytorch.org/docs/stable/torchvision/models.html
converter --input_model wide_resnet50_2.onnx \
--reverse_input_channels \
--mean_values [123.675,116.28,103.53] \
--scale_values [58.395,57.12,57.375]

echo "Generating VNNX for V1000 configuration..."
generate_vnnx -x wide_resnet50_2.xml  -c V1000 -f ../../sample_images -o torchvision_wide_resnet50_2.vnnx

echo "Running Simulation..."
python $VBX_SDK/example/python/imagenet.py torchvision_wide_resnet50_2.vnnx ../../oreo.jpg

deactivate
