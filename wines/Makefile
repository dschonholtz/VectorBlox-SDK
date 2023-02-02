# A makefile to help do various model manipulation

SHELL := /bin/bash

# get the root dir of the vectorblox repo one level up from the current dir
ROOT_DIR=$(shell dirname $(shell dirname $(realpath $(lastword $(MAKEFILE_LIST)))))

# get the current dir and save it as a var
WINES_DIR=$(shell pwd)
NP_DIR="$(WINES_DIR)/np_data"
H5_DATA_PATH="$(WINES_DIR)/preseiz-13089010103_41368_2_sample9.h5"
H5_MODEL_PATH="$(WINES_DIR)/pat_25302.pruneCNN12.h5"
SAVED_VNNX_PATH="$(WINES_DIR)/saved_model.vnnx"
SAVED_XML_PATH="$(WINES_DIR)/saved_model.xml"


# do cleanup
clean:
	cd ${WINES_DIR} && bash cleanup.sh

# Test h5 has a side effect of creating the input data.
# that needs to be cleaned up, but for now, it is a dependency
# of other testing.
test_h5:
	python3 test_h5_model.py \
		--input_data "${H5_DATA_PATH}" \
		--input_npy_dir "${NP_DIR}" \
		--model "${H5_MODEL_PATH}" \
		--output_file "${WINES_DIR}/h5_model_out.json" \
		--nuke_data FALSE

model_convert: clean test_h5
	cd ${ROOT_DIR} && source "setup_vars.sh" && \
		source "setup_vars.sh" && \
		cd ${WINES_DIR} && \
		./wines_model_convertor.sh "${NP_DIR}"

test_xml: #model_convert
	python3 SeizNetInfer.py \
		--h5 "${H5_DATA_PATH}" \
		--model "${SAVED_XML_PATH}" \
		--output "${WINES_DIR}/xml_model_out.json"

test_vnnx: model_convert
	python3 SeizNetInfer.py \
		--h5 "${H5_DATA_PATH}" \
		--model "${SAVED_VNNX_PATH}" \
		--output "${WINES_DIR}/vnnx_model_out.json"

default:
	make test_vnnx

