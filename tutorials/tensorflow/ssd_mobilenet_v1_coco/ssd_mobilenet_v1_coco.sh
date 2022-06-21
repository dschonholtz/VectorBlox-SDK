
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

echo "Downloading ssd_mobilenet_v1_coco..."
omz_downloader --name ssd_mobilenet_v1_coco
wget https://raw.githubusercontent.com/openvinotoolkit/openvino/master/tools/mo/openvino/tools/mo/front/tf/ssd_v2_support.json

echo "Running Model Optimizer..."
# model details @ https://github.com/openvinotoolkit/open_model_zoo/tree/2021.4.2/models/public/ssd_mobilenet_v1_coco/
mo --input_model=public/ssd_mobilenet_v1_coco/ssd_mobilenet_v1_coco_2018_01_28/frozen_inference_graph.pb \
--framework tf \
--input_shape [1,300,300,3] \
--reverse_input_channels \
--input=image_tensor \
--output=BoxPredictor_0/BoxEncodingPredictor/BiasAdd,BoxPredictor_0/ClassPredictor/BiasAdd,BoxPredictor_1/BoxEncodingPredictor/BiasAdd,BoxPredictor_1/ClassPredictor/BiasAdd,BoxPredictor_2/BoxEncodingPredictor/BiasAdd,BoxPredictor_2/ClassPredictor/BiasAdd,BoxPredictor_3/BoxEncodingPredictor/BiasAdd,BoxPredictor_3/ClassPredictor/BiasAdd,BoxPredictor_4/BoxEncodingPredictor/BiasAdd,BoxPredictor_4/ClassPredictor/BiasAdd,BoxPredictor_5/BoxEncodingPredictor/BiasAdd,BoxPredictor_5/ClassPredictor/BiasAdd \
--tensorflow_object_detection_api_pipeline_config=public/ssd_mobilenet_v1_coco/ssd_mobilenet_v1_coco_2018_01_28/pipeline.config \
--transformations_config=ssd_v2_support.json \
--static_shape

echo "Generating VNNX for V1000 configuration..."
generate_vnnx -x frozen_inference_graph.xml  -c V1000 -f ../../sample_images -o ssd_mobilenet_v1_coco.vnnx --bias-correction

echo "Running Simulation..."
python $VBX_SDK/example/python/ssdv2.py ssd_mobilenet_v1_coco.vnnx ../../dog.jpg

deactivate
