import os
import h5py
from sklearn.preprocessing import normalize
import numpy as np
import shutil

def read_and_normalize_h5(h5_file):
    with h5py.File(h5_file, 'r') as f:
        x = f['data'][()]
        x = np.transpose(x)
        x = normalize(x, norm='l2', axis=1, copy=True, return_norm=False)
        x = np.expand_dims(x, -1)
        print(x.shape)
    return x
    

def save_h5_data_to_dir(input_file_path, output_dir, replace_existing=False):
    # nuke the existing data if it is there.
    if replace_existing:
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
    elif os.path.exists(output_dir):
        print("Output directory already exists.  Not replacing.")
        return
    input_data = read_and_normalize_h5(input_file_path)

    # make the dir
    os.makedirs(output_dir, exist_ok=True)
    for i, chunk in enumerate(input_data):
        input_file =  str(i) + ".npy"
        input_chunk_name = os.path.join(output_dir, input_file)
        # add a dim to the chunk
        chunk = np.expand_dims(chunk, 0)
        np.save(input_chunk_name, chunk)
    
def read_np_data_from_dir(input_dir):
    input_data = []
    for file in os.listdir(input_dir):
        if file.endswith(".npy"):
            input_file = os.path.join(input_dir, file)
            input_chunk = np.load(input_file)
            input_data.append(input_chunk)
    return input_data
