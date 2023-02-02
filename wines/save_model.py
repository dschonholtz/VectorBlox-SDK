import tensorflow as tf
from tensorflow.keras.layers import Conv2D, Reshape, MaxPooling2D, InputLayer, LeakyReLU
from tensorflow.keras import Model
import argparse
import numpy as np
import os


def make_new_model(old_model):
    """
    This iterates through the old model's layers.
    It replaces each conv1d layer with a conv2d layer where the extra dimension is of size 1.
    It also updates the size of all other layers to account for the extra dimension.
    Then it copies all of the weights from all of the layers of the old model to the new model.
    """
    # make a new model
    model = tf.keras.models.clone_model(
        old_model, input_tensors=None, clone_function=None
    )
    # iterate through the new model's layers and add the extra dimension
    x = None
    for i in range(len(model.layers)):
        layer = model.layers[i]
        if layer.__class__.__name__ == 'Conv1D':
            # get the config of the layer
            config = layer.get_config()
            # update the config
            print(config)
            config['kernel_size'] = (1, config['kernel_size'][0])
            config['strides'] = (1, config['strides'][0])
            # config['padding'] = 'valid'
            config['dilation_rate'] = (1, config['dilation_rate'][0])
            if 'batch_input_shape' in config:
                config['batch_input_shape'] = (config['batch_input_shape'][0], 1, config['batch_input_shape'][1], config['batch_input_shape'][2])
            # create a new conv2d layer with the updated config
            new_layer = Conv2D(**config)
            # copy the weights from the old layer to the new layer
            x = new_layer(x)
        elif layer.__class__.__name__ == 'Reshape':
            # get the config of the layer
            config = layer.get_config()
            # update the config
            print('target shape')
            print(config['target_shape'])
            config['target_shape'] = (config['target_shape'][0], 1, config['target_shape'][1])
            # create a new reshape layer with the updated config
            new_layer = Reshape(**config)
            # replace the old layer with the new layer
            x = new_layer(x)
        # handle maxpooling layers
        elif layer.__class__.__name__ == 'MaxPooling1D':
            # get the config of the layer
            config = layer.get_config()
            # update the config
            config['pool_size'] = (1, config['pool_size'][0])
            config['strides'] = (1, config['strides'][0])
            # config['padding'] = 'valid'
            # config['batch_input_shape'] = (config['batch_input_shape'][0], 1, config['batch_input_shape'][1], config['batch_input_shape'][2])
            # create a new maxpooling layer with the updated config
            new_layer = MaxPooling2D(**config)
            x = new_layer(x)
        # handle InputLayer
        elif layer.__class__.__name__ == 'InputLayer':
            # get the config of the layer
            config = layer.get_config()
            # update the config
            config['batch_input_shape'] = (config['batch_input_shape'][0], 1, config['batch_input_shape'][1], config['batch_input_shape'][2])
            # create a new input layer with the updated config
            input_layer = InputLayer(**config)
            x = input_layer.output
        # handle dropout layers. Just skip them.
        elif layer.__class__.__name__ == 'Dropout':
            continue
        # handle LeakyReLU layers. Set the output size correctly
        elif layer.__class__.__name__ == 'LeakyReLU':
            # get the config of the layer
            config = layer.get_config()
            # update the config
            # create a new input layer with the updated config
            new_layer = LeakyReLU(**config)
            x = new_layer(x)
        else:
            # just copy the layer
            x = layer(x)
            print("Layer type not handled: ", layer.__class__.__name__)

    model = Model(inputs=input_layer.input, outputs=x)
    # copy the weights from the old model to the new model
    new_model_idx = 0
    for i in range(len(old_model.layers)):
        weights = old_model.layers[i].get_weights()
        if old_model.layers[i].__class__.__name__ == 'Conv1D':
            weights_shape = weights[0].shape
            weights = [np.reshape(weights[0], (1, weights_shape[0], weights_shape[1], weights_shape[2])), weights[1]]
        # skip the dropout layers
        if old_model.layers[i].__class__.__name__ == 'Dropout':
            continue
        model.layers[new_model_idx].set_weights(weights)
        new_model_idx += 1

    return model

def main():
    parser = argparse.ArgumentParser()
    # default file is the current directory and the pat_25302.pruneCNN12.h5 file
    default_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'pat_25302.pruneCNN12.h5')
    parser.add_argument('--model', default=default_file, help='model path')
    args = parser.parse_args()
    old_model = tf.keras.models.load_model(args.model)
    old_model.summary()

    # Add the conv2d model before all other existing layers
    # Then squeeze one dimension from the output of the conv2d layer
    # This is to make the model compatible with the MO tool and generate_vnnx tool

    model = make_new_model(old_model)
    # model.make()
    model.summary()

    # remove the extension from the model name
    # concat the list of dot separated strings except the last one
    list_strs = args.model.split('.')[0:-1]
    model_name = '.'.join(list_strs)

    model.save('MO_COMPLIANT_' + model_name)


if __name__ == '__main__':
    main()