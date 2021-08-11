import argparse
import json
import numpy as np
import glob
import os
import sys
import onnx
import onnx.utils
from onnx import checker, helper
from . import onnx_helper 
from .openvino_parse_xml import parse_openvino_xml
from .onnx_infer import onnx_infer, onnx_activations_batched, onnx_random_infer, onnx_random_input, load_input
from .utils import *
from .onnx_kld import get_optimal_threshold, get_valid_kld


np.set_printoptions(suppress=True, precision=4, linewidth=120)


def trunc(arr, decimals=8):
    # return np.trunc(arr*10**decimals)/(10**decimals)
    return arr


def gather_stats(onnx_model, nodes, input, count, scale, kld_threshold=False):

    valid_kld = {}
    if kld_threshold:
        valid_kld = get_valid_kld(onnx_model)
    # print(valid_kld.keys())

    if os.path.isdir(input):
        inputs = []
        extensions = ['*.jpg', '*.png', '*.jpeg', '*.npy']
        extensions += [e.upper() for e in extensions]
        for ext in extensions:
            inputs += sorted(glob.glob(os.path.join(input, ext)))
        if count:
            inputs = inputs[:count]
        input_shape = onnx_helper.get_model_input_shape(onnx_model)
        input_arrays = np.vstack([load_input(i, scale, input_shape) for i in inputs])
    else:
        input_arrays = np.load(input)
    stats = onnx_activations_batched(onnx_model, input_arrays, stats_only=True, histogram_dict=valid_kld)

    stats_list = []
    for output in sorted(stats.keys()):
        if 'hist' in stats[output]:
            (hist, hist_edges, min_val, max_val, th) = stats[output]['hist']
            _, _, _, opt = get_optimal_threshold(stats[output]['hist'], valid_kld[output])

            stats_list.append({'id':output,
                              'mean': stats[output]['mean'],
                              'max': stats[output]['max'],
                              'min': stats[output]['min'],
                              'threshold': opt})
        else:
            stats_list.append({'id':output,
                              'mean': stats[output]['mean'],
                              'max': stats[output]['max'],
                              'min': stats[output]['min']})

    if not (nodes is None):
        for node in nodes:
            node.set_stats_by_id(stats_list)
        return nodes
    else:
        return stats_list


def as_int(x):
    values = [int(_) for _ in x.split(',')]

    if len(values) == 1:
        return values[0]
    else:
        return values


def io(vinode):
    inputs = ['{}'.format(_) for _ in vinode._from]
    if vinode.weights:
        inputs += ['W{}'.format(vinode.id)]
    if vinode.biases:
        inputs += ['b{}'.format(vinode.id)]
    outputs = ['{}'.format(vinode.id)]

    return inputs, outputs


def gen_pad_10(vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    pads_begin = vinodes[int(inputs[1])]
    pads_end = vinodes[int(inputs[2])]
    if 'pad_value' in vinode.data:
        pad_value = float(vinode.data['pad_value'])
    else:
        pad_value = float(vinodes[int(inputs[-1])].data['arr'].tolist()[0])
    inputs = inputs[:1]

    pads = pads_begin.data['arr'].tolist() + pads_end.data['arr'].tolist()
    if pads[0] != 0:
        errmsg="ERROR: Node {}: pad channels at beginning of buffer not supported\n"
        sys.stderr.write(errmsg.format(vinode.name))
        sys.exit(1)
    if vinode.data['pad_mode'] != 'constant':
        errmsg="ERROR: Node {}: Only pad mode 'constant' is supported'"
        sys.stderr.write(errmsg.format(vinode.name))
        sys.exit(1)
    if pad_value != 0.0:
        errmsg="ERROR: Node {}: Only pad value of zero"
        sys.stderr.write(errmsg.format(vinode.name))
        sys.exit(1)

    value_tensor = onnx.helper.make_tensor('value_{}'.format(buf),
                                           onnx.TensorProto.FLOAT,
                                           (1,),
                                           [0.])

    pads_tensor = onnx.helper.make_tensor('pad_{}'.format(vinode.id),
                                          onnx.TensorProto.INT64,
                                          np.asarray(pads).shape,
                                          pads)
    inits.append(pads_tensor)
    inits.append(value_tensor)

    inputs.append('pad_{}'.format(vinode.id))
    inputs.append('value_{}'.format(vinode.id))

    node = onnx.helper.make_node('Pad',
                                 inputs=inputs,
                                 outputs=outputs,
                                 mode='constant',
                                 name=str(vinode.id))
    nodes.append(node)
    return nodes, inits


def gen_input(vinode):
    nodes, inits = [], []
    return nodes, inits


def gen_conv(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    pads = as_int(vinode.data['pads_begin']) + as_int(vinode.data['pads_end'])

    node = onnx.helper.make_node(
            'Conv',
            inputs=inputs,
            outputs=outputs,
            group = as_int(vinode.data['group']),
            strides = as_int(vinode.data['strides']),
            dilations = as_int(vinode.data['dilations']),
            kernel_shape = as_int(vinode.data['kernel']),
            pads = pads,
            name = str(vinode.id),
            )
    nodes.append(node)


    if vinode.weights:
        length = vinode.weights['arr'].shape[0]
        kernel_shape = as_int(vinode.data['kernel'])
        output_channels = as_int(vinode.data['output'])

        input_channels = int(length / output_channels / kernel_shape[0] / kernel_shape[1])
        weights_shape = (output_channels, input_channels, kernel_shape[0], kernel_shape[1])

        tensor = onnx.helper.make_tensor('W{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                weights_shape,
                trunc(vinode.weights['arr']).tolist(),
                )
        inits.append(tensor)
    if vinode.biases:
        tensor = onnx.helper.make_tensor('b{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                (as_int(vinode.data['output']),),
                trunc(vinode.biases['arr']).tolist(),
                )
        inits.append(tensor)


    return nodes, inits
def auto_pad_calc(auto_pad,input_shape,kernel_size,stride,dilations):
    pads=[0 for i in range(4)]
    if auto_pad in ("SAME_UPPER","SAME_LOWER"):
        def calc_pad(in_shape,kern,stride):
            out_shape = np.ceil(in_shape/stride)
            pad = (out_shape-1)*stride + kern -in_shape
            return pad
        
        dilated_kernel_size0 = (kernel_size[0]-1)*dilations[0]+1
        dilated_kernel_size1 = (kernel_size[1]-1)*dilations[1]+1

        pad = calc_pad(input_shape[2],dilated_kernel_size0,stride[0])
        pads[0] = np.ceil(pad/2)
        pads[2] = np.floor(pad/2)
        
        pad = calc_pad(input_shape[3],dilated_kernel_size1,stride[1])
        pads[1] = np.ceil(pad/2)
        pads[3] = np.floor(pad/2)
        if auto_pad == "SAME_UPPER":
            #swap back and front
            pads = pads[2:] + pads[:2]
    return [int(p) for p in pads]
        
        

def gen_conv_10(vinode, bias_vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    node_id = vinode.id
    if bias_vinode:
        bias_inputs, bias_outputs = io(bias_vinode)
        node_id = bias_vinode.id

    buf = outputs[0]
    node_outputs = outputs
    if bias_vinode:
        buf = bias_outputs[0]
        node_outputs = bias_outputs

    weights = vinodes[int(inputs[1])]
    inputs = inputs[:-1] + ['W{}'.format(node_id)]
    if bias_vinode:
        biases = vinodes[int(bias_inputs[1])]
        inputs += ['b{}'.format(node_id)]
    
    if 'auto_pad' in vinode.data:
        if vinode.data['auto_pad'] == 'explicit':
            pads = as_int(vinode.data['pads_begin']) + as_int(vinode.data['pads_end'])
        else:
            auto_pad = vinode.data['auto_pad'].upper()
            pads = auto_pad_calc(auto_pad,
                                 vinode.input[0],
                                 as_int(weights.data['shape'])[-2:],
                                 as_int(vinode.data['strides']),
                                 as_int(vinode.data['dilations']))
    else:
        auto_pad = None
        pads = as_int(vinode.data['pads_begin']) + as_int(vinode.data['pads_end'])

    node = onnx.helper.make_node(
        'Conv',
        inputs = inputs,
        outputs = node_outputs,
        strides = as_int(vinode.data['strides']),
        dilations = as_int(vinode.data['dilations']),
        kernel_shape = as_int(weights.data['shape'])[-2:],
        pads = pads,
        name = str(node_id),
    )
    nodes.append(node)

    if weights:
        tensor = onnx.helper.make_tensor('W{}'.format(node_id),
                onnx.TensorProto.FLOAT,
                as_int(weights.data['shape']),
                trunc(weights.data['arr']).tolist(),
                )
        inits.append(tensor)

    if bias_vinode and biases:
        tensor = onnx.helper.make_tensor('b{}'.format(node_id),
                onnx.TensorProto.FLOAT,
                as_int(biases.data['shape'])[1:2],
                trunc(biases.data['arr']).tolist(),
                )
        inits.append(tensor)


    return nodes, inits


def gen_group_conv_scaleshift(vinode, bias_vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    node_id = vinode.id
    if bias_vinode:
        bias_inputs, bias_outputs = io(bias_vinode)
        node_id = bias_vinode.id

    buf = bias_outputs[0]
    node_outputs = bias_outputs

    assert(len(inputs) == 2)
    constant_input = [is_constant(vinodes[int(i)], vinodes) for i in inputs]
    if constant_input[0]:
        weights = vinodes[int(inputs[0])]
        inputs = inputs[1:]
        idims = vinode.input[1]
    elif constant_input[1]:
        weights = vinodes[int(inputs[1])]
        inputs = inputs[:-1]
        idims = vinode.input[0]
    inputs = inputs + ['W{}'.format(node_id)]

    if bias_vinode:
        biases = vinodes[int(bias_inputs[1])]
        inputs += ['b{}'.format(node_id)]

    kernels = idims[1]
    kernel_shape = [kernels,1,1,1]
    biases_shape = as_int(biases.data['shape'])
    weights_shape = as_int(weights.data['shape'])
    if weights_shape[1] == kernels:
        w = weights.data['arr'].tolist()
    else:
        w = [weights.data['arr'] for _ in range(kernels)]
    if biases_shape[1] == kernels:
        b = biases.data['arr'].tolist()
    else:
        b = [biases.data['arr'] for _ in range(kernels)]

    node = onnx.helper.make_node(
        'Conv',
        inputs = inputs,
        outputs = node_outputs,
        group = kernels,
        kernel_shape = [1,1],
        name = str(node_id),
    )
    nodes.append(node)

    if weights:
        tensor = onnx.helper.make_tensor('W{}'.format(node_id),
                onnx.TensorProto.FLOAT,
                kernel_shape,
                w,
                )
        inits.append(tensor)

    if bias_vinode and biases:
        tensor = onnx.helper.make_tensor('b{}'.format(node_id),
                onnx.TensorProto.FLOAT,
                [kernels],
                b,
                )
        inits.append(tensor)

    return nodes, inits


def gen_group_conv_10(vinode, bias_vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    node_id = vinode.id
    if bias_vinode:
        bias_inputs, bias_outputs = io(bias_vinode)
        node_id = bias_vinode.id

    buf = outputs[0]
    node_outputs = outputs
    if bias_vinode:
        buf = bias_outputs[0]
        node_outputs = bias_outputs

    weights = vinodes[int(inputs[1])]
    inputs = inputs[:-1] + ['W{}'.format(node_id)]
    if bias_vinode:
        biases = vinodes[int(bias_inputs[1])]
        inputs += ['b{}'.format(node_id)]

    if 'auto_pad' in vinode.data:
        if vinode.data['auto_pad'] == 'explicit':
            pads = as_int(vinode.data['pads_begin']) + as_int(vinode.data['pads_end'])
        else:
            auto_pad = vinode.data['auto_pad'].upper()
            pads = auto_pad_calc(auto_pad,
                                 vinode.input[0],
                                 as_int(weights.data['shape'])[-2:],
                                 as_int(vinode.data['strides']),
                                 as_int(vinode.data['dilations']))
    else:
        auto_pad = None
        pads = as_int(vinode.data['pads_begin']) + as_int(vinode.data['pads_end'])

    kernel_shape = as_int(weights.data['shape'])
    kernel_shape = [kernel_shape[0] * kernel_shape[1]] + kernel_shape[2:3] + kernel_shape[-2:]
    node = onnx.helper.make_node(
        'Conv',
        inputs = inputs,
        outputs = node_outputs,
        group = as_int(weights.data['shape'])[0],
        strides = as_int(vinode.data['strides']),
        dilations = as_int(vinode.data['dilations']),
        kernel_shape = as_int(weights.data['shape'])[-2:],
        pads = pads,
        name = str(node_id),
    )
    nodes.append(node)


    if weights:
        tensor = onnx.helper.make_tensor('W{}'.format(node_id),
                onnx.TensorProto.FLOAT,
                kernel_shape,
                trunc(weights.data['arr']).tolist(),
                )
        inits.append(tensor)

    if bias_vinode and biases:
        tensor = onnx.helper.make_tensor('b{}'.format(node_id),
                onnx.TensorProto.FLOAT,
                as_int(biases.data['shape'])[1:2],
                trunc(biases.data['arr']).tolist(),
                )
        inits.append(tensor)

    return nodes, inits


def gen_maxpool_10(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    pads = as_int(vinode.data['pads_begin']) + as_int(vinode.data['pads_end'])

    ceil_mode = 0
    if 'rounding_type' in vinode.data and vinode.data['rounding_type'] == 'ceil':
        ceil_mode = 1

    node = onnx.helper.make_node(
            'MaxPool',
            inputs=inputs,
            outputs=outputs,
            strides = as_int(vinode.data['strides']),
            kernel_shape = as_int(vinode.data['kernel']),
            # auto_pad = "SAME_UPPER",
            pads = pads,
            ceil_mode = ceil_mode,
            name = str(vinode.id),
            )
    nodes.append(node)

    return nodes, inits


def gen_avgpool_10(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    pads = as_int(vinode.data['pads_begin']) + as_int(vinode.data['pads_end'])

    ceil_mode = 0
    if 'rounding_type' in vinode.data and vinode.data['rounding_type'] == 'ceil':
        ceil_mode = 1

    node = onnx.helper.make_node(
            'AveragePool',
            inputs=inputs,
            outputs=outputs,
            strides = as_int(vinode.data['strides']),
            kernel_shape = as_int(vinode.data['kernel']),
            # auto_pad = "SAME_UPPER",
            pads = pads,
            ceil_mode = ceil_mode,
            name = str(vinode.id),
            )
    nodes.append(node)

    return nodes, inits


def gen_reduce_10(vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    idims = vinode.input[0]
    odims = vinode.output[0]

    node = vinodes[int(inputs[1])]
    if 'arr' in node.data:
        reduction = node.data['arr'].tolist()
    else:
        reduction = None

    keep_dims = True
    if 'keep_dims' in vinode.data and vinode.data['keep_dims'] == 'False':
        keep_dims = False
    assert(not keep_dims or odims[-2:] == (1, 1))

    if reduction and reduction[-1] != len(idims)-1:
        node = onnx.helper.make_node(
                'ReduceMean',
                inputs=inputs[:1],
                outputs=outputs,
                axes=reduction,
                keepdims=keep_dims,
                name=str(vinode.id),
                )
        nodes.append(node)
    else:
        if keep_dims:
                node = onnx.helper.make_node(
                        'AveragePool',
                        inputs=inputs[:1],
                        outputs=outputs,
                        kernel_shape = list(idims[-2:]),
                        name = str(vinode.id),
                        )
                nodes.append(node)
        else:
            buf = outputs[0]
            _buf = outputs[0] + '_f'
            flatten_output = '{}_flat'.format(vinode.id)
            node = onnx.helper.make_node(
                    'AveragePool',
                    inputs=inputs[:1],
                    outputs=[_buf],
                    kernel_shape = list(idims[-2:]),
                    name = _buf,
                    )
            nodes.append(node)
            node = onnx.helper.make_node(
                    'Flatten',
                    inputs=[_buf],
                    outputs=outputs,
                    name = buf,
                    )
            nodes.append(node)

    return nodes, inits


def gen_multiply_10(vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    assert(len(inputs) == 2)
    constant_input = [is_constant(vinodes[int(i)], vinodes) for i in inputs]
    if constant_input[0]:
        weights = vinodes[int(inputs[0])]
        inputs = inputs[1:]
    elif constant_input[1]:
        weights = vinodes[int(inputs[1])]
        inputs = inputs[:-1]
    else:
        print('error, non-const multiply not implemented')

    inputs = inputs + ['W{}'.format(vinode.id)]

    node = onnx.helper.make_node(
        'Mul',
        inputs=inputs,
        outputs=outputs,
        name=buf,
    )
    nodes.append(node)

    if weights:
        tensor = onnx.helper.make_tensor('W{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                as_int(weights.data['shape'])[1:],
                trunc(weights.data['arr']).tolist(),
                )
        inits.append(tensor)

    return nodes, inits


def gen_add_10(vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    is_const = False
    for input in inputs:
        input_vinode = [_ for _ in vinodes if str(_.id) == input][0]
        if input_vinode.type == 'Const':
            is_const = True

    if not is_const:
        node = onnx.helper.make_node(
                'Sum',
                inputs=inputs,
                outputs=outputs,
                name = str(vinode.id),
                )
        nodes.append(node)
    else:
        biases = vinodes[int(inputs[1])]
        if biases:
            inputs = inputs[:-1] + ['b{}'.format(vinode.id)]

        node = onnx.helper.make_node(
            'Add',
            inputs=inputs,
            outputs=outputs,
            name=buf,
        )
        nodes.append(node)

        if biases:
            tensor = onnx.helper.make_tensor('b{}'.format(vinode.id),
                    onnx.TensorProto.FLOAT,
                    as_int(biases.data['shape'])[1:],
                    trunc(biases.data['arr']).tolist(),
                    )
            inits.append(tensor)

    return nodes, inits


def gen_relu(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    if vinode.data and 'negative_slope' in vinode.data:
        slope = float(vinode.data['negative_slope'])
        node = onnx.helper.make_node(
                'LeakyRelu',
                inputs=inputs,
                outputs=outputs,
                name = str(vinode.id),
                alpha=slope,
                )

    else:
        node = onnx.helper.make_node(
                'Relu',
                inputs=inputs,
                outputs=outputs,
                name = str(vinode.id),
                )

    nodes.append(node)

    return nodes, inits


def gen_prelu(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    inputs = inputs[:1]

    assert(int(vinode.data['channel_shared']) == 0)
    slope = onnx.helper.make_tensor('slope_{}'.format(vinode.id),
                                    onnx.TensorProto.FLOAT,
                                    (vinode.weights['arr'].shape[0], 1, 1),
                                    vinode.weights['arr'].tolist())
    inits.append(slope)
    inputs.append('slope_{}'.format(vinode.id))

    node = onnx.helper.make_node(
            'PRelu',
            inputs=inputs,
            outputs=outputs,
            name = str(vinode.id),
            )
    nodes.append(node)

    return nodes, inits

def gen_prelu_10(vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    data_node = vinodes[int(inputs[1])]
    if data_node.type != 'Const':
        sys.stderr.write("ERROR:Non-constant weights in Prelu node {} not supported\n".format(vinode.name))
        sys.exit(1)

    inputs = inputs[0:1]

    if data_node.data['shape'] == '1':
        slope = float(data_node.data['arr'][0])
        node = onnx.helper.make_node(
                'LeakyRelu',
                inputs=inputs,
                outputs=outputs,
                name = str(vinode.id),
                alpha=slope,
                )
        nodes.append(node)
    else:

        slope = onnx.helper.make_tensor('slope_{}'.format(vinode.id),
                                        onnx.TensorProto.FLOAT,
                                        (data_node.data['arr'].shape[0], 1, 1),
                                        data_node.data['arr'].tolist())
        inits.append(slope)

        inputs.append('slope_{}'.format(vinode.id))

        node = onnx.helper.make_node(
                'PRelu',
                inputs=inputs,
                outputs=outputs,
                name = str(vinode.id),
                )
        nodes.append(node)

    return nodes, inits


def gen_elu(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    alpha = float(vinode.data['alpha'])
    node = onnx.helper.make_node(
            'Elu',
            inputs=inputs,
            outputs=outputs,
            name = str(vinode.id),
            alpha=alpha,
            )
    nodes.append(node)

    return nodes, inits


def gen_const(vinode):
    nodes, inits = [], []

    tensor = onnx.helper.make_tensor('{}'.format(vinode.id),
            onnx.TensorProto.FLOAT,
            vinode.custom['arr'].shape,
            vinode.custom['arr'].tolist(),
            )
    inits.append(tensor)

    return nodes, inits


# this function is no longer used with the darknet_to_onnx tool
def gen_extract(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    stride, stride = as_int(vinode.data['strides'])
    assert(stride == 2)
    dims = vinode.input[0]
    dims = tuple([-1] + list(dims)[1:])

    reshape_1 = np.array([dims[0], dims[1], dims[2]//stride, stride, dims[3]//stride, stride], dtype=np.int64)
    transpose_1 = [0,1,2,4,3,5]
    tensor = onnx.helper.make_tensor('shape_1_{}'.format(vinode.id),
            onnx.TensorProto.INT64,
            reshape_1.shape,
            reshape_1.tolist(),
            )
    inits.append(tensor)
    node = onnx.helper.make_node(
            'Reshape',
            inputs=[inputs[0], 'shape_1_{}'.format(vinode.id)],
            outputs=['reshape_1_{}'.format(vinode.id)],
            name = str('reshape_1_{}'.format(vinode.id))
            )
    nodes.append(node)
    node = onnx.helper.make_node(
            'Transpose',
            inputs=['reshape_1_{}'.format(vinode.id)],
            outputs=['transpose_1_{}'.format(vinode.id)],
            perm = transpose_1,
            name = str('transpose_1_{}'.format(vinode.id))
            )
    nodes.append(node)

    reshape_2 = np.array([dims[0], dims[1], dims[2]//stride*dims[2]//stride, stride*stride], dtype=np.int64)
    transpose_2 = [0,1,3,2]
    tensor = onnx.helper.make_tensor('shape_2_{}'.format(vinode.id),
            onnx.TensorProto.INT64,
            reshape_2.shape,
            reshape_2.tolist(),
            )
    inits.append(tensor)
    node = onnx.helper.make_node(
            'Reshape',
            inputs=['transpose_1_{}'.format(vinode.id), 'shape_2_{}'.format(vinode.id)],
            outputs=['reshape_2_{}'.format(vinode.id)],
            name = str('reshape_2_{}'.format(vinode.id))
            )
    nodes.append(node)
    node = onnx.helper.make_node(
            'Transpose',
            inputs=['reshape_2_{}'.format(vinode.id)],
            outputs=['transpose_2_{}'.format(vinode.id)],
            perm = transpose_2,
            name = str('transpose_2_{}'.format(vinode.id))
            )
    nodes.append(node)

    reshape_3 = np.array([dims[0], dims[1], stride*stride, dims[2]//stride, dims[2]//stride], dtype=np.int64)
    transpose_3 = [0,2,1,3,4]
    tensor = onnx.helper.make_tensor('shape_3_{}'.format(vinode.id),
            onnx.TensorProto.INT64,
            reshape_3.shape,
            reshape_3.tolist(),
            )
    inits.append(tensor)
    node = onnx.helper.make_node(
            'Reshape',
            inputs=['transpose_2_{}'.format(vinode.id), 'shape_3_{}'.format(vinode.id)],
            outputs=['reshape_3_{}'.format(vinode.id)],
            name = str('reshape_3_{}'.format(vinode.id))
            )
    nodes.append(node)
    node = onnx.helper.make_node(
            'Transpose',
            inputs=['reshape_3_{}'.format(vinode.id)],
            outputs=['transpose_3_{}'.format(vinode.id)],
            perm = transpose_3,
            name = str('transpose_3_{}'.format(vinode.id))
            )
    nodes.append(node)

    reshape_4 = np.array([dims[0], dims[1]*stride*stride, dims[2]//stride, dims[2]//stride], dtype=np.int64)
    tensor = onnx.helper.make_tensor('shape_4_{}'.format(vinode.id),
            onnx.TensorProto.INT64,
            reshape_4.shape,
            reshape_4.tolist(),
            )
    inits.append(tensor)
    node = onnx.helper.make_node(
            'Reshape',
            inputs=['transpose_3_{}'.format(vinode.id), 'shape_4_{}'.format(vinode.id)],
            outputs=outputs,
            name = str(vinode.id)
            )
    nodes.append(node)

    return nodes, inits


def gen_flatten(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    node = onnx.helper.make_node(
            'Flatten',
            inputs=inputs[:1],  # TODO
            outputs=outputs,
            name = str(vinode.id),
            )
    nodes.append(node)

    return nodes, inits


def gen_clamp(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]


    min_clip = onnx.helper.make_tensor('min_{}'.format(vinode.id),
            onnx.TensorProto.FLOAT,
            (),
            vals=np.float32(vinode.data['min']).tobytes(),
            raw=True,
            )
    inits.append(min_clip)
    inputs.append('min_{}'.format(vinode.id))

    max_clip = onnx.helper.make_tensor('max_{}'.format(vinode.id),
            onnx.TensorProto.FLOAT,
            (),
            vals=np.float32(vinode.data['max']).tobytes(),
            raw=True,
            )
    inits.append(max_clip)
    inputs.append('max_{}'.format(vinode.id))

    node = onnx.helper.make_node(
            'Clip',
            inputs=inputs,
            outputs=outputs,
            name = str(vinode.id),
            )
    nodes.append(node)

    return nodes, inits


def gen_interp(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    factor = float(vinode.data['factor'])
    if factor == 1.0:
        #for some reason this node was inserted in deeplabv3,
        #exchange it for identity
        return gen_identity(vinode)
    mode = 'linear'
    roi = onnx.helper.make_tensor('roi{}'.format(vinode.id),
            onnx.TensorProto.FLOAT,
            (0,), [])


    inits.append(roi)
    inputs.append('roi{}'.format(vinode.id))
    scales = np.array([1.0, 1.0, factor, factor], dtype=np.float32)
    tensor = onnx.helper.make_tensor('s{}'.format(vinode.id),
            onnx.TensorProto.FLOAT,
            scales.shape,
            scales.tolist(),
            )
    inits.append(tensor)
    inputs.append('s{}'.format(vinode.id))

    node = onnx.helper.make_node('Resize',
                                 inputs=inputs,
                                 outputs=outputs,
                                 name = str(vinode.id),
                                 mode = mode,
                                 coordinate_transformation_mode="align_corners")
    nodes.append(node)

    return nodes, inits


def gen_interpolate(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    inputs = inputs[:1]
    idims = vinode.input[0]
    odims = vinode.output[0]
    factor0 = float(odims[-2]) / float(idims[-2])
    factor1 = float(odims[-1]) / float(idims[-1])
    assert(factor0 == factor1)
    factor = factor0

    if factor == 1.0:
        return gen_identity(vinode)
    mode = vinode.data['mode']
    assert(mode in ['linear', 'nearest'])

    roi = onnx.helper.make_tensor('roi{}'.format(vinode.id),
            onnx.TensorProto.FLOAT,
            (0,), [])

    inits.append(roi)
    inputs.append('roi{}'.format(vinode.id))
    scales = np.array([1.0, 1.0, factor, factor], dtype=np.float32)
    tensor = onnx.helper.make_tensor('s{}'.format(vinode.id),
            onnx.TensorProto.FLOAT,
            scales.shape,
            scales.tolist(),
            )
    inits.append(tensor)
    inputs.append('s{}'.format(vinode.id))

    node = onnx.helper.make_node('Resize',
                                 inputs=inputs,
                                 outputs=outputs,
                                 name = str(vinode.id),
                                 mode = mode,
                                 coordinate_transformation_mode="align_corners")
    nodes.append(node)

    return nodes, inits


def gen_resample(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    assert(vinode.data['type'] == 'caffe.ResampleParameter.NEAREST')
    assert(vinode.data['height'] == '0')
    assert(vinode.data['width'] == '0')
    assert(vinode.data['antialias'] == '0')

    factor = vinode.data['factor']
    mode = 'nearest'
    roi = onnx.helper.make_tensor('roi{}'.format(vinode.id),
                                  onnx.TensorProto.FLOAT,
                                  (0,), [])


    inits.append(roi)
    inputs.append('roi{}'.format(vinode.id))

    scales = np.array([1.0, 1.0, factor, factor], dtype=np.float32)

    tensor = onnx.helper.make_tensor('s{}'.format(vinode.id),
            onnx.TensorProto.FLOAT,
            scales.shape,
            scales.tolist(),
            )
    inits.append(tensor)
    inputs.append('s{}'.format(vinode.id))

    node = onnx.helper.make_node(
            'Resize',
            inputs=inputs,
            outputs=outputs,
            name = str(vinode.id),
            mode = mode,
            )
    nodes.append(node)


    return nodes, inits


def gen_pooling(vinode):
    # TODO confirm padding
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    pads = as_int(vinode.data['pads_begin']) + as_int(vinode.data['pads_end'])

    ceil_mode = 0
    if 'rounding_type' in vinode.data and vinode.data['rounding_type'] == 'ceil':
        ceil_mode = 1

    if vinode.data['pool-method'] == 'max':
        node = onnx.helper.make_node(
                'MaxPool',
                inputs=inputs,
                outputs=outputs,
                strides = as_int(vinode.data['strides']),
                kernel_shape = as_int(vinode.data['kernel']),
                # auto_pad = "SAME_UPPER",
                pads = pads,
                ceil_mode = ceil_mode,
                name = str(vinode.id),
                )
        nodes.append(node)
    elif vinode.data['pool-method'] == 'avg':
        count_include_pad = 0
        if 'exclude-pad' in vinode.data and vinode.data['exclude-pad'] == 'false':
            count_include_pad = 1

        node = onnx.helper.make_node(
                'AveragePool',
                inputs=inputs,
                outputs=outputs,
                strides = as_int(vinode.data['strides']),
                kernel_shape = as_int(vinode.data['kernel']),
                pads = pads,
                ceil_mode = ceil_mode,
                count_include_pad = count_include_pad,
                name = str(vinode.id),
                )
        nodes.append(node)
    else:
        print('WARNING', vinode.data['pool-method'])

    return nodes, inits


def gen_eltwise(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]



    if vinode.data['operation'] == 'sum':
        node = onnx.helper.make_node(
                'Sum',
                inputs=inputs,
                outputs=outputs,
                name = str(vinode.id),
                )
        nodes.append(node)
    else:
        raise RuntimeError('Node {} Error: Unsupported eltwise operation'.format(vinode.id))

    return nodes, inits


def gen_concat(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]
    axis = int(vinode.data['axis'])

    if axis != 1:
        errmsg="ERROR: Node {}: Concatenating on axis {}. Concat nodes only suppported with axis == 1\n"
        sys.stderr.write(errmsg.format(vinode.name,axis))
        sys.exit(1)

    node = onnx.helper.make_node(
            'Concat',
            inputs=inputs,
            outputs=outputs,
            axis=axis,
            name=buf,
            )
    nodes.append(node)

    return nodes, inits


def gen_norm(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]
    inputs = inputs[:1]

    alpha = float(vinode.data['alpha'])
    beta = float(vinode.data['beta'])
    nsize = int(vinode.data['size'])

    node = onnx.helper.make_node(
        'LRN',
        inputs=inputs,
        outputs=outputs,
        alpha=alpha,
        beta=beta,
        size=nsize,
        name=buf,
    )
    nodes.append(node)

    return nodes, inits


def gen_scaleshift(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]
    _buf = outputs[0] + '_ss'

    if vinode.weights and vinode.biases:
        mul_inputs = [inputs[0], inputs[1]]
        mul_outputs = [_buf]
        add_inputs = [_buf, inputs[2]]

        node = onnx.helper.make_node(
            'Mul',
            inputs=mul_inputs,
            outputs=mul_outputs,
            name=_buf,
        )
        nodes.append(node)

        node = onnx.helper.make_node(
            'Add',
            inputs=add_inputs,
            outputs=outputs,
            name=buf,
        )
        nodes.append(node)
    elif vinode.weights:
        node = onnx.helper.make_node(
            'Mul',
            inputs=inputs,
            outputs=outputs,
            name=buf,
        )
        nodes.append(node)
    elif vinode.biases:
        node = onnx.helper.make_node(
            'Add',
            inputs=inputs,
            outputs=outputs,
            name=buf,
        )
        nodes.append(node)

    assert(vinode.weights['arr'].shape == vinode.biases['arr'].shape)
    assert(vinode.weights['arr'].ndim == 1)
    shape = (vinode.weights['arr'].shape[0], 1, 1)

    if vinode.weights:
        tensor = onnx.helper.make_tensor('W{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                shape,
                trunc(vinode.weights['arr']).tolist(),
                )
        inits.append(tensor)

    if vinode.biases:
        tensor = onnx.helper.make_tensor('b{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                shape,
                trunc(vinode.biases['arr']).tolist(),
                )
        inits.append(tensor)

    return nodes, inits


def gen_reshape(vinode):
    nodes, inits = [], []

    if len(one_elem(vinode.output)):

        inputs, outputs = io(vinode)
        buf = outputs[0]

        inputs = inputs[:1]
        inputs.append('reshape_{}'.format(vinode.id))

        node = onnx.helper.make_node(
            'Reshape',
            inputs=inputs,
            outputs=outputs,
            name=buf,
        )
        nodes.append(node)


        val = list(one_elem(vinode.output))
        val = [-1] + val[1:]
        tensor = onnx.helper.make_tensor('reshape_{}'.format(vinode.id),
                onnx.TensorProto.INT64,
                np.asarray(vinode.output[0]).shape,
                val,
                )
        inits.append(tensor)

    return nodes, inits


def gen_tile(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    idims = vinode.input[0]
    odims = vinode.output[0]

    tile = [int(o/i) for o,i in zip(odims,idims)]
    tile_tensor = onnx.helper.make_tensor('tile_{}'.format(vinode.id),
                                          onnx.TensorProto.INT64,
                                          np.asarray(tile).shape,
                                          tile)

    inputs = inputs[:1]
    inits.append(tile_tensor)
    inputs.append('tile_{}'.format(vinode.id))

    node = onnx.helper.make_node(
            'Tile',
            inputs=inputs,
            outputs=outputs,
            name = str(vinode.id),
            )
    nodes.append(node)

    return nodes, inits


def gen_mul1(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    mul_buf = 'W{}'.format(vinode.id)
    mul_inputs = [inputs[0], mul_buf]

    tensor = onnx.helper.make_tensor(mul_buf,
            onnx.TensorProto.FLOAT,
            (1,),
            [1.],
            )
    inits.append(tensor)
    node = onnx.helper.make_node(
        'Mul',
        inputs=mul_inputs,
        outputs=outputs,
        name=buf,
    )
    nodes.append(node)

    return nodes, inits

def gen_power(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    assert(float(vinode.data['power']) == 1.0)
    shift = float(vinode.data['shift'])
    scale = float(vinode.data['scale'])

    mul_buf = 'W{}'.format(vinode.id)
    tensor = onnx.helper.make_tensor(mul_buf,
            onnx.TensorProto.FLOAT,
            (1,),
            [scale],
            )
    inits.append(tensor)

    bias_buf = 'b{}'.format(vinode.id)
    tensor = onnx.helper.make_tensor(bias_buf,
            onnx.TensorProto.FLOAT,
            (1,),
            [shift],
            )
    inits.append(tensor)

    _buf = outputs[0] + '_ss'
    mul_inputs = [inputs[0], mul_buf]
    mul_outputs = [_buf]
    add_inputs = [_buf, bias_buf]

    node = onnx.helper.make_node(
        'Mul',
        inputs=mul_inputs,
        outputs=mul_outputs,
        name=_buf,
    )
    nodes.append(node)

    node = onnx.helper.make_node(
        'Add',
        inputs=add_inputs,
        outputs=outputs,
        name=buf,
    )
    nodes.append(node)

    return nodes, inits

def gen_fullyconnected(vinode, prev_vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]
    _buf = outputs[0] + '_f'

    dims = vinode.output[0]
    prev_dims = prev_vinode.output[0]
    if len(dims) != len(prev_dims):
        flatten_inputs = [inputs[0]]
        flatten_outputs = [_buf]
        gemm_inputs = [_buf] + inputs[1:]

        node = onnx.helper.make_node(
            'Flatten',
            inputs=flatten_inputs,
            outputs=flatten_outputs,
            name=_buf,
        )
        nodes.append(node)

        node = onnx.helper.make_node(
            'Gemm',
            inputs=gemm_inputs,
            outputs=outputs,
            transB=1,
            name=buf,
        )
        nodes.append(node)
    else:
        node = onnx.helper.make_node(
            'Gemm',
            inputs=inputs,
            outputs=outputs,
            transB=1,
            name=buf,
        )
        nodes.append(node)

    length = vinode.weights['arr'].shape[0]
    output_size = as_int(vinode.data['out-size'])
    input_size = int(length / output_size)

    if vinode.weights:
        tensor = onnx.helper.make_tensor('W{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                (output_size, input_size),
                trunc(vinode.weights['arr']).tolist(),
                )
        inits.append(tensor)
    if vinode.biases:
        tensor = onnx.helper.make_tensor('b{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                (output_size,),
                trunc(vinode.biases['arr']).tolist(),
                )
        inits.append(tensor)

    return nodes, inits

def gen_matmul(vinode, prev_vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]
    _buf = outputs[0] + '_f'

    dims = vinode.output[0]
    prev_dims = prev_vinode.output[0]

    if len(dims) != len(prev_dims):
        flatten_inputs = [inputs[0]]
        flatten_outputs = [_buf]
        gemm_inputs = [_buf] + inputs[1:]

        node = onnx.helper.make_node(
            'Flatten',
            inputs=flatten_inputs,
            outputs=flatten_outputs,
            name=_buf,
        )
        nodes.append(node)

        node = onnx.helper.make_node(
            'Gemm',
            inputs=gemm_inputs,
            outputs=outputs,
            transB=1,
            name=buf,
        )
        nodes.append(node)
    else:
        node = onnx.helper.make_node(
            'Gemm',
            inputs=inputs,
            outputs=outputs,
            transB=1,
            name=buf,
        )
        nodes.append(node)

    length = vinode.weights['arr'].shape[0]
    output_size = as_int(vinode.data['out-size'])
    input_size = int(length / output_size)

    if vinode.weights:
        tensor = onnx.helper.make_tensor('W{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                (output_size, input_size),
                trunc(vinode.weights['arr']).tolist(),
                )
        inits.append(tensor)
    if vinode.biases:
        tensor = onnx.helper.make_tensor('b{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                (output_size,),
                trunc(vinode.biases['arr']).tolist(),
                )
        inits.append(tensor)

    return nodes, inits


def gen_matmul_10(vinode, bias_vinode, prev_vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    dims = vinode.output[0]
    prev_dims = prev_vinode.output[0]

    inputs[0] = str(prev_vinode.id)
    if bias_vinode:
        bias_inputs, bias_outputs = io(bias_vinode)
        outputs = bias_outputs
    buf = outputs[0]
    _buf = outputs[0] + '_f'

    weights = vinodes[int(inputs[1])]
    inputs = inputs[:-1] + ['W{}'.format(vinode.id)]
    if bias_vinode:
        biases = vinodes[int(bias_inputs[1])]
        inputs += ['b{}'.format(vinode.id)]

    if len(dims) != len(prev_dims):
        flatten_inputs = [inputs[0]]
        flatten_outputs = [_buf]
        gemm_inputs = [_buf] + inputs[1:]

        node = onnx.helper.make_node(
            'Flatten',
            inputs=flatten_inputs,
            outputs=flatten_outputs,
            name=_buf,
        )
        nodes.append(node)

        node = onnx.helper.make_node(
            'Gemm',
            inputs=gemm_inputs,
            outputs=outputs,
            transB=1,
            name=buf,
        )
        nodes.append(node)
    else:
        node = onnx.helper.make_node(
            'Gemm',
            inputs=inputs,
            outputs=outputs,
            transB=1,
            name=buf,
        )
        nodes.append(node)

    
    if weights:
        tensor = onnx.helper.make_tensor('W{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                as_int(weights.data['shape']),
                trunc(weights.data['arr']).tolist(),
                )
        inits.append(tensor)

    if bias_vinode and biases:
        tensor = onnx.helper.make_tensor('b{}'.format(vinode.id),
                onnx.TensorProto.FLOAT,
                as_int(biases.data['shape'])[1:2],
                trunc(biases.data['arr']).tolist(),
                )
        inits.append(tensor)

    return nodes, inits


def gen_identity(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    node = onnx.helper.make_node('Identity', inputs[:1], outputs, name = str(vinode.id))
    nodes.append(node)

    return nodes, inits


def gen_topk(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    axis = int(vinode.data['axis'])
    mode = vinode.data['mode']

    idim = vinode.input[0]
    if axis!= 1:
        errmsg="ERROR: Node {}: TopK is only supported on axis 1\n"
        sys.stderr.write(errmsg.format(vinode.name))
        sys.exit(1)
    maps = idim[axis]
    if maps > 256:
        errmsg="ERROR: Node {}: TopK is only supported on less than 256 maps\n"
        sys.stderr.write(errmsg.format(vinode.name))
        sys.exit(1)

    if mode != 'max':
        errmsg="ERROR: Node {}: TopK is only supported with mode == max\n"
        sys.stderr.write(errmsg.format(vinode.name))
        sys.exit(1)

    buf = outputs[0]
    _buf = outputs[0] + '_ss'
    argmax_inputs = [inputs[0]]
    cast_inputs = [_buf]

    node = onnx.helper.make_node('ArgMax', argmax_inputs, [_buf], name = _buf, axis=axis)
    nodes.append(node)

    node = onnx.helper.make_node(
        'Cast',
        inputs=cast_inputs,
        outputs=outputs,
        name=buf,
        to=int(onnx.TensorProto.FLOAT)
    )
    nodes.append(node)

    return nodes, inits


def gen_softmax(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]
    axis = int(vinode.data['axis'])
    input_shape = one_elem(vinode.input)
    batch_size_axis = 0
    for i,s in enumerate(input_shape):
        if i==axis or i==batch_size_axis:
            continue
        if s == 1:
            continue
        errmsg="ERROR: Node {}: input shape {} with axis {} not supported for softmax\n"
        sys.stderr.write(errmsg.format(vinode.name,input_shape,axis))
        sys.exit(1)

    node = onnx.helper.make_node(
            'Softmax',
            inputs = inputs,
            outputs = outputs,
            axis=axis,
            name = str(vinode.id),
            )
    nodes.append(node)

    return nodes, inits


def gen_sigmoid(vinode):
    nodes, inits = [], []
    inputs, outputs = io(vinode)
    buf = outputs[0]

    node = onnx.helper.make_node(
            'Sigmoid',
            inputs = inputs,
            outputs = outputs,
            name = str(vinode.id),
            )
    nodes.append(node)

    return nodes, inits


def gen_transpose(vinode, vinodes):
    nodes, inits = [], []
    inputs, outputs = io(vinode)

    input_shape = vinode.input[0]
    output_shape = vinode.output[0]
    
    perm_node = vinodes[int(inputs[1])]
    perm = perm_node.data['arr'].tolist()
    test_array = np.random.rand(*input_shape)
    if np.array_equal(test_array.reshape(output_shape), test_array.transpose(perm)):
        #transpose is equivalent to reshape
        return gen_reshape(vinode)

    # if (perm not in ([0,2,3,1],)) and ('reorg' not in vinode.name.lower()):
    #     sys.stderr.write("ERROR:Node {}: permutation '{}' not supported\n".format(vinode.name,perm))
    #     sys.exit(1)
    inputs = inputs[:1]
    node = onnx.helper.make_node('Transpose',
                                 inputs = inputs,
                                 outputs = outputs,
                                 perm = perm,
                                 name = str(vinode.id))
    nodes.append(node)
    return nodes, inits


def is_constant(vinode, vinodes):
    if vinode.type in ['ShapeOf', 'Const']:
        return True
    elif vinode.type in ['Gather', 'Concat']:
        inputs, outputs = io(vinode)
        return all([is_constant(vinodes[int(i)], vinodes) for i in inputs])

    return False


def gen_graph_io(vinodes, nodes):
    inputs = []
    outputs = []
    
    for n in nodes:
        previous_nodes = onnx_helper.get_previous_nodes(nodes, n)
        if len(previous_nodes) == 0:
            #is input node
            vinode = one_elem([vi for vi in vinodes if str(vi.id) == n.name])
            if vinode.type == 'Add':
                #sometimes the node is named after the biasing vinode after it
                #so we need to fine that actual node before it.
                possible_vinode = [vi for vi in vinodes if len(vi._to) and vi.id == vinode._from[0]]
                if len(possible_vinode)!=0:
                    vinode = one_elem(possible_vinode)

            #TODO Handle more than one input on an input node.
            try:
                constant_inputs = [is_constant(vinodes[int(i)], vinodes) for i in io(vinode)[0]]
                shape = vinode.input[0]
                if constant_inputs[0]:
                    shape = vinode.input[1]
            except:
                shape = vinode.output[0]
            inputs.append(onnx.helper.make_tensor_value_info('{}'.format(n.input[0]), onnx.TensorProto.FLOAT, shape))
        next_nodes = []
        for no in n.output:
            next_nodes.extend(onnx_helper.get_node_inputs(nodes,no))
        if len(next_nodes) == 0:
            #is output node
            vinode = one_elem([vi for vi in vinodes if str(vi.id) == n.name])
            #TODO Handle more than one output on an output node.
            shape = vinode.output[0]
            outputs.append(onnx.helper.make_tensor_value_info('{}'.format(n.output[0]), onnx.TensorProto.FLOAT, shape))
    return inputs, outputs


def gen_onnx(vinodes):
    graph_nodes = []
    graph_inits = []

    prev_vinode = None
    vidx = 0
    while vidx < len(vinodes):
        vinode = vinodes[vidx]
        if vidx+1 < len(vinodes):
            next_vinode = vinodes[vidx+1]
        else:
            next_vinode = None
        if vinode.type == 'Parameter':
            nodes, inits = gen_input(vinode)
        elif vinode.type == 'PReLU':
            nodes, inits = gen_prelu_10(vinode, vinodes)
        elif vinode.type in ['Result', 'ShapeOf', 'Convert', 'Range']:
            nodes, inits = [],[]
        elif vinode.type == 'Gather':
            if is_constant(vinode, vinodes):
                nodes, inits = [],[]
            else:
                raise NotImplementedError('Non-const {} not implemented'.format(vinode.type))
                continue
        elif vinode.type == 'Const':
            nodes, inits = [], []
            vidx += 1
            continue
        elif vinode.type == 'Multiply':
            if len(vinodes) > vidx+2 and vinodes[vidx+1].type == 'Const' and vinodes[vidx+2].type == 'Add':
                bias_vinode = vinodes[vidx+2]
                vidx +=2
                nodes, inits = gen_group_conv_scaleshift(vinode, bias_vinode, vinodes)
            else:
                nodes, inits = gen_multiply_10(vinode, vinodes)
        elif vinode.type == 'Add':
            nodes, inits = gen_add_10(vinode, vinodes)
        elif vinode.type == 'Convolution':
            bias_vinode = None
            if len(vinodes) > vidx+2 and vinodes[vidx+1].type == 'Const' and vinodes[vidx+2].type == 'Add':
                bias_vinode = vinodes[vidx+2]
                vidx +=2
            nodes, inits = gen_conv_10(vinode, bias_vinode, vinodes)
        elif vinode.type == 'GroupConvolution':
            bias_vinode = None
            if len(vinodes) > vidx+2 and vinodes[vidx+1].type == 'Const' and vinodes[vidx+2].type == 'Add':
                bias_vinode = vinodes[vidx+2]
                vidx +=2
            nodes, inits = gen_group_conv_10(vinode, bias_vinode, vinodes)
        elif vinode.type == 'MatMul':
            bias_vinode = None
            if len(vinodes) > vidx+2 and vinodes[vidx+1].type == 'Const' and vinodes[vidx+2].type == 'Add':
                bias_vinode = vinodes[vidx+2]
                vidx +=2
            nodes, inits = gen_matmul_10(vinode, bias_vinode, prev_vinode, vinodes)
        elif vinode.type == 'ReLU':
            nodes, inits = gen_relu(vinode)
        elif vinode.type == 'Concat':
            if is_constant(vinode, vinodes):
                nodes, inits = [],[]
            else:
                nodes, inits = gen_concat(vinode)
        elif vinode.type == 'Squeeze':
            nodes, inits = gen_reshape(vinode)
        elif vinode.type == 'Unsqueeze':
            nodes, inits = gen_reshape(vinode)
        elif vinode.type == 'ReduceMean':
            nodes, inits = gen_reduce_10(vinode, vinodes)
        elif vinode.type == 'AvgPool':
            nodes, inits = gen_avgpool_10(vinode)
        elif vinode.type == 'MaxPool':
            nodes, inits = gen_maxpool_10(vinode)
        elif vinode.type == 'SoftMax':
            nodes, inits = gen_softmax(vinode)
        elif vinode.type == 'Sigmoid':
            nodes, inits = gen_sigmoid(vinode)
        elif vinode.type == 'Reshape':
            nodes, inits = gen_reshape(vinode)
        elif vinode.type == 'RegionYolo':
            nodes, inits = gen_reshape(vinode)
        elif vinode.type == 'Flatten':
            nodes, inits = gen_flatten(vinode)
        # elif vinode.type == 'ReorgYolo':
        #     nodes, inits = gen_reorg_yolo(vinode)
        elif vinode.type == 'ExtractImagePatches':
            nodes, inits = gen_extract(vinode)
        elif vinode.type == 'Interpolate':
            nodes, inits = gen_interpolate(vinode)
        elif vinode.type == 'Transpose':
            nodes, inits = gen_transpose(vinode, vinodes)
        elif vinode.type == 'Clamp':
            nodes, inits = gen_clamp(vinode)
        elif vinode.type == 'LRN':
            nodes, inits = gen_norm(vinode)
        elif vinode.type == 'TopK':
            nodes, inits = gen_topk(vinode)
        elif vinode.type == 'Tile':
            nodes, inits = gen_tile(vinode)
        elif vinode.type == 'Pad':
            nodes, inits = gen_pad_10(vinode, vinodes)
        else:
            raise NotImplementedError('{} not implemented'.format(vinode.type))
            continue
        prev_vinode = vinodes[vidx]
        vidx += 1
        graph_nodes += nodes
        graph_inits += inits
    return graph_nodes, graph_inits


def gen_pad_graph():

    X = onnx.helper.make_tensor_value_info('X', onnx.TensorProto.FLOAT, (1,2))
    Y = onnx.helper.make_tensor_value_info('Y', onnx.TensorProto.FLOAT, (1,4))


    node = onnx.helper.make_node(
            'Pad',
            ['X'],
            ['Y'],
            mode='constant',
            pads=[0,1,0,1],
            value=1.5,
            )
    nodes = [node]
    inputs = [X]
    outputs = [Y]
    initializers = []

    graph = onnx.helper.make_graph(
            nodes,
            'pad-graph',
            inputs,
            outputs,
            initializers,
            )

    return graph


def gen_softmax_graph():

    X = onnx.helper.make_tensor_value_info('X', onnx.TensorProto.FLOAT, (1,1000))
    Y = onnx.helper.make_tensor_value_info('Y', onnx.TensorProto.FLOAT, (1,1000))


    node = onnx.helper.make_node(
            'Softmax',
            ['X'],
            ['Y'],
            )
    nodes = [node]
    inputs = [X]
    outputs = [Y]
    initializers = []

    graph = onnx.helper.make_graph(
            nodes,
            'softmax-graph',
            inputs,
            outputs,
            initializers,
            )

    return graph


def convert_openvino_xml_to_onnx(vinodes, graph_name, version):
    assert(version == '10')
    nodes, inits = gen_onnx(vinodes)
    inputs, outputs = gen_graph_io(vinodes, nodes)

    for input in inputs:
        input.type.tensor_type.shape.dim[0].dim_param = "N"
    for output in outputs:
        output.type.tensor_type.shape.dim[0].dim_param = "N"

    graph = onnx.helper.make_graph(
            nodes,
            graph_name,
            inputs,
            outputs,
            inits,
            )

    return graph


def save_stats(nodes, output_file):
    stats = []
    for node in nodes:
        if not (node.min is None) and not (node.max is None):
            if not (node.threshold is None):
                stats.append({
                    'name': node.name, 'id': node.id,
                    'min': node.min.tolist(), 'max': node.max.tolist(), 'threshold': node.threshold.tolist(),
                    'input': node.input, 'output': node.output})
            elif not (node.mean is None):
                stats.append({
                    'name': node.name, 'id': node.id,
                    'min': node.min.tolist(), 'max': node.max.tolist(), 'mean': node.mean.tolist(),
                    'input': node.input, 'output': node.output})
            else:
                stats.append({
                    'name': node.name, 'id': node.id,
                    'min': node.min.tolist(), 'max': node.max.tolist(),
                    'input': node.input, 'output': node.output})

    with open(output_file, 'w') as f:
        json.dump(stats, f)


def cut_after_node(nodes, cut):
    cut_nodes = []
    for n in nodes:
        if n.name == cut:
            max_id = n.id

    for n in nodes:
        if n.id < max_id:
            cut_nodes.append(n)
        elif n.id == max_id:
            n._to = []
            cut_nodes.append(n)

    return cut_nodes


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('xml')
    parser.add_argument('-s', '--stats', action='store_true')
    parser.add_argument('-r', '--random', action='store_true')
    parser.add_argument('-i', '--image')
    parser.add_argument('-t', '--topk', action='store_true')
    parser.add_argument('-j', '--json', action='store_true')
    parser.add_argument('-c', '--cut')
    args = parser.parse_args()

    model_name = args.xml.split('.xml')[0]
    onnx_name = '{}.onnx'.format(model_name)

    nodes, ir_version = parse_openvino_xml(args.xml)
    if args.cut:
        nodes = cut_after_node(nodes, args.cut)

    graph = convert_openvino_xml_to_onnx(nodes, model_name, ir_version)
    onnx_helper.onnx_save_model(graph, onnx_name)

    if args.stats: # save layer statistics
        save_stats(nodes, model_name)

    if args.random: # test random input
        input_array = onnx_random_input(onnx_name)
        output = onnx_infer(onnx_name, input_array)
        if args.topk:
            imagenet.print_topk(output.flatten())

    if args.image: # test input image
        input_shape =  onnx_helper.get_model_input_shape(onnx_name)
        input_array = load_input(args.image, 1./255., input_shape)
        output = onnx_infer(onnx_name, input_array)
        if args.topk:
            imagenet.print_topk(output.flatten())
        if args.json:
            with open('{}.json'.format(onnx_name), 'w') as f:
                json.dump(output.flatten().tolist(), f)
