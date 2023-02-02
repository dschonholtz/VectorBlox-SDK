"""
This is a script based on the example/python/yoloIfer.py script.

This script is used to run inference on a SeizNet model. 
It takes 1d input and outputs a binary classification on whether or not someone is likely to have a seizure in the near future.

The model is a vnnx file, the input is a 1d array of 1024 floats, and the output is a 1d array of 2 floats.

We read the input in from a h5 file, and write the output to a h5 file.
"""

import argparse
import numpy as np
import os
import json

import h5py
from sklearn.preprocessing import normalize

from vbx.generate.openvino_infer import openvino_infer, get_model_input_shape as get_xml_input_shape
from vbx.generate.onnx_infer import onnx_infer, load_input
from vbx.generate.onnx_helper import get_model_input_shape as get_onnx_input_shape
from vbx.generate.utils import pad_input
import vbx.sim


def read_and_normalize_h5(h5_file):
    with h5py.File(h5_file, 'r') as f:
        x = f['data'][()]
        x = np.transpose(x)
        x = normalize(x, norm='l2', axis=1, copy=True, return_norm=False)
        x = np.expand_dims(x, -1)
        print(x.shape)
    return x

def get_vnnx_io_shapes(vnxx):
    with open(vnxx, 'rb') as mf:
        model = vbx.sim.Model(mf.read())
    return model.input_dims[0], model.output_dims


def vnnx_infer(vnxx_model, modelInput):
    with open(vnxx_model, "rb") as mf:
        model = vbx.sim.Model(mf.read())
    modelInput = modelInput #* 0.24357412206139598
    # modelInput = np.expand_dims(modelInput, axis=0)
    # modelInput *= 255
    # modelInput.clip(0, 128)
    print('model input: ' + str(modelInput))
    flattened = (modelInput.flatten()).astype('int8')
    outputList = model.run([flattened])
    print(model.output_scale_factor)
    outputs = [out * scale for out, scale in zip(outputList, model.output_scale_factor)]

    bw = model.get_bandwidth_per_run()
    print("Bandwidth per run = {} Bytes ({:.3} MB/s at 100MHz)".format(bw,bw/100E6))
    print("Estimated {} seconds at 100MHz".format(model.get_estimated_runtime(100E6)))
    print("If running at another frequency, scale these numbers appropriately")

    return outputs

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument('-m', '--model')
    parser.add_argument('-h5', '--h5', help='h5 file to read input data from')
    parser.add_argument('-o', '--output')
    args = parser.parse_args()
    
    # input
    input_data = read_and_normalize_h5(args.h5)
    input_array = np.expand_dims(input_data, axis=1)
    print(input_array.shape)
    
    # model
    modelOutput = {
        "output": [],
    }

    if args.model.endswith('.vnnx'):
        input_shape, _ = get_vnnx_io_shapes(args.model)
        for in_val in input_array:
            outputs = vnnx_infer(args.model, in_val)
            # save the outputs to a json file
            modelOutput['output'].append(outputs[0].tolist())

    elif args.model.endswith('.xml'):
        weights=args.model.replace('.xml', '.bin')
        input_shape = get_xml_input_shape(args.model, weights)
        for in_val in input_array:
            in_val = np.reshape(in_val, input_shape)
            output = openvino_infer(args.model, in_val)[0]
            modelOutput['output'].append(output[0].tolist())
    else:
        raise ValueError("Unsupported model type: {}".format(args.model))
    with open(args.output, 'w') as f:
        json.dump(modelOutput, f)