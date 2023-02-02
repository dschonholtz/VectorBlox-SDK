"""
A simple script to load the h5 model and run inference on it using the h5 input data.
"""

import argparse
import numpy as np
import json
import tensorflow as tf

from utils import save_h5_data_to_dir, read_np_data_from_dir

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument('--input_data', help='path to input data')
    parser.add_argument('--input_npy_dir', help='path to input data when it gets saved as npy files')
    parser.add_argument('--model', help='path to model')
    parser.add_argument('--output_file', help='path to output data')
    parser.add_argument('--nuke_data', help='delete the input data after running inference', default=False)
    args = parser.parse_args()

    save_h5_data_to_dir(args.input_data, args.input_npy_dir, replace_existing=args.nuke_data)
    input_data = read_np_data_from_dir(args.input_npy_dir)
    
    model = tf.keras.models.load_model(args.model)

    # run inference
    output = []
    for i, chunk in enumerate(input_data):
        output.append(model(chunk).numpy().tolist())

    # save output to json file
    with open(args.output_file, 'w') as f:
        # convert the output tensor to a list and save it to a json file
        json.dump(output, f)
