
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

# Take a parameter for the input numpy data
if [ -z "$1" ]; then
    echo "No input numpy data provided. Exiting"
    exit 1
else
    INPUT_NPY="$1"
fi

echo "Checking and Activating VBX Python Environment..."
if [ -z $VBX_SDK ]; then
    echo "\$VBX_SDK not set. Please run 'source setup_vars.sh' from the SDK's root folder" && exit 1
fi
source $VBX_SDK/vbx_env/bin/activate

python "./save_model.py" --model "pat_25302.pruneCNN12.h5"



MODEL_OUTPUT_DIR="MO_COMPLIANT_pat_25302.pruneCNN12"

echo "Running Model Optimizer..."
mo --saved_model_dir="${MODEL_OUTPUT_DIR}" \
--input_shape "[1,1,1024,1]" \

# --input "StatefulPartitionedCall[1 1 1024 1]" \
# --log_level=DEBUG
# --scale_values [255.] \
# --reverse_input_channels \

MODEL_NAME_FILE="saved_model"

echo "Generating VNNX for V1000 configuration..."
generate_vnnx -x "${MODEL_NAME_FILE}.xml" -c V1000 -f "${INPUT_NPY}"  -o "${MODEL_NAME_FILE}.vnnx" --bias-correction

echo "Running Simulation..."
# python3 -m "./SeizNetInfer.py"

deactivate
