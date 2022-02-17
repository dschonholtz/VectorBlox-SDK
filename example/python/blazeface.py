import vbx.sim
import argparse
import os
import numpy as np
import cv2
from  vbx.postprocess.blazeface import blazeface

from vbx.generate.openvino_infer import openvino_infer, get_model_input_shape as get_xml_input_shape
from vbx.generate.onnx_infer import onnx_infer, load_input
from vbx.generate.onnx_helper import get_model_input_shape as get_onnx_input_shape

def plot_detections(img, detections, with_keypoints=True):
        output_img = img


        print("Found %d faces" % len(detections))
        for i in range(len(detections)):
            ymin = detections[i][ 0] * img.shape[0]
            xmin = detections[i][ 1] * img.shape[1]
            ymax = detections[i][ 2] * img.shape[0]
            xmax = detections[i][ 3] * img.shape[1]
            p1 = (int(xmin),int(ymin))
            p2 = (int(xmax),int(ymax))
            print(p1,p2)
            cv2.rectangle(output_img, p1, p2, (0,50,0))

            if with_keypoints:
                for k in range(6):
                    kp_x = int(detections[i, 4 + k*2    ] * img.shape[1])
                    kp_y = int(detections[i, 4 + k*2 + 1] * img.shape[0])
                    cv2.circle(output_img,(kp_x,kp_y),1,(0,0,255))
        cv2.imwrite("output.png",output_img)

        return output_img

def vnnx_infer(vnnx_model, input_array):
    model = vbx.sim.model.Model(open(vnnx_model,"rb").read())

    flattened = input_array.flatten().astype('uint8')
    outputs = model.run([flattened])
    outputs = [o/(1<<16) for o in outputs]

    bw = model.get_bandwidth_per_run()
    print("Bandwidth per run = {} Bytes ({:.3} MB/s at 100MHz)".format(bw,bw/100E6))
    print("Estimated {} seconds at 100MHz".format(model.get_estimated_runtime(100E6)))
    print("If running at another frequency, scale these numbers appropriately")

    return outputs

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model')
    parser.add_argument('image')
    parser.add_argument('-a', '--anchors', default='BlazeFace-PyTorch/anchors.npy')
    parser.add_argument('-s', '--size', type=int, default=128)
    parser.add_argument('--height', type=int, default=128, help='expected height of image')
    parser.add_argument('--width', type=int, default=128, help='expected width of image')
    parser.add_argument('--channels', type=int, default=3, help='number of channels of image')
    parser.add_argument('-t', '--threshold', type=float, default=0.75)

    args = parser.parse_args()

    if args.model.endswith('.vnnx'):
        input_shape = (args.channels, args.height, args.width)
        input_array = load_input(args.image, 1., input_shape)
        outputs = vnnx_infer(args.model, input_array)
    elif args.model.endswith('.xml'):
        weights=args.model.replace('.xml', '.bin')
        input_shape = get_xml_input_shape(args.model, weights)
        input_array = load_input(args.image, 1., input_shape)
        outputs = openvino_infer(args.model, input_array)
    elif args.model.endswith('.onnx'):
        input_shape = get_onnx_input_shape(args.model)
        input_array = load_input(args.image, 1., input_shape)  
        outputs = onnx_infer(args.model, input_array)

    if len(outputs) == 4:
        a = np.concatenate((outputs[0], outputs[1]))
        b = np.concatenate((outputs[2], outputs[3]))
    else:
        a = outputs[0]
        b = outputs[1]

    anchors = np.load(args.anchors)
    detections = blazeface(a, b, anchors, args.size, args.threshold)
    plot_detections(cv2.imread(args.image), detections[0])




if __name__ == "__main__":
    main()
