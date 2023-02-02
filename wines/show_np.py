"""
A simple python script to print each numpy script in the given directory using the argparse lib
"""

import argparse
import os
import numpy as np

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_dir", help="The directory containing the numpy files", default="np_data")
    args = parser.parse_args()
    input_dir = args.input_dir
    for file in os.listdir(input_dir):
        if file.endswith(".npy"):
            print(file)
            vals = np.load(os.path.join(input_dir, file)) * 256
            print(vals)
            # print the max and min of each array
            print("Max: ", np.max(vals))
            print("Min: ", np.min(vals))

if __name__ == "__main__":
    main()
