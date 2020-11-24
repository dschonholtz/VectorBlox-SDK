/*!
 * \file
 * \brief Data structure definitions for VectorBlox ONNX
 */

#ifndef VNNX_TYPES_H
#define VNNX_TYPES_H
#include <stdlib.h>
#include <stdint.h>
typedef uint64_t obj_off_t;
#define STRUCT_PACKED struct __attribute__((packed,aligned(4)))
typedef enum {
	CALC_TYPE_UINT8,
	CALC_TYPE_INT8,
	CALC_TYPE_INT16,
	CALC_TYPE_INT32,
	CALC_TYPE_UNKNOWN
} calc_type_e;
typedef enum{
	CONV_SUBGRAPH,
	GEMM_SUBGRAPH,
	SUM_SUBGRAPH,
	IDENTITY_SUBGRAPH,
	LRN_SUBGRAPH,
	TRANSPOSE_SUBGRAPH,
	SOFTMAX_SUBGRAPH,
	RESIZE_SUBGRAPH,
	REORG_SUBGRAPH,
	ARGMAX_SUBGRAPH,
	UNKNOWN_SUBGRAPH
} subgraph_type_e;

typedef enum{
    RESIZE_NEAREST,
    RESIZE_LINEAR
} resize_mode_e;

typedef enum {
	GLOBAL_AVGPOOL_I8 =0,  ///< GLOBAL_AVERAGE with bytes
	GLOBAL_AVGPOOL_I16 =1,  ///< GLOBAL_AVERAGE with halfs
	ABS_I8 =2,
	ABS_I16=3,
	CLIP_I8=4,
	CLIP_I16=5,
	AVGPOOL_I8=6,  ///< AVERAGE POOL with bytes
	AVGPOOL_I16=7,  ///< AVERAGE POOL with halfs
	MAXPOOL_U8 =8,  ///< MAXPOOL with bytes and stride or size greater than 2
	MAXPOOL_I8 =9,  ///< MAXPOOL with bytes and stride or size greater than 2
	MAXPOOL_I16=10, ///< MAXPOOL with halfwords and stride or size greater than 2
	CAST_I16_I8=11,  ///< Convert type from halfs to bytes
	CAST_I16_I32=12,  ///< Convert type from halfs to bytes
	CAST_I32_I16=13,  ///< Convert type from words to halfs
	CAST_U8_I16=14,  ///< Convert type from ubytes to halfs
	CAST_U8_I8=15,  ///< Convert type from ubytes to bytes
	CAST_I8_I16=16,  ///< Convert type from bytes to halfs
	CAST_I8_I32=17,  ///< Convert type from bytes to halfs
	LEAKYRELU_I8=18, ///< Leaky Relu on bytes
	LEAKYRELU_I16=19, ///< Leaky Relu on halfwords
	RELU_I8=20, ///< Relu on bytes
	RELU_I16=21, ///< Relu on halfwords
	PRELU_I8=22, ///< PRelu on bytes
	PRELU_I16=23, ///< PRelu on halfwords
	PADCONST_U8=24,  ///< Pad Const with bytes
	PADCONST_I8=25,  ///< Pad Const with bytes
	PADCONST_I16=26, ///< Pad Const with halfwords
	MUL_BC3_I8=27,  ///< Multiply const with bytes
	MUL_BC3_I16=28, ///< Multiply const with halfwords
	MUL_BC3_U8=29,  ///< Multiply const with unsigned bytes
	MUL_BC3_U16=30, ///< Multiply const with unsigned halfwords
	MUL_BC2_I8=31,  ///< Multiply consts per channel with bytes
	MUL_BC2_I16=32, ///< Multiply consts per channel with halfwords
	ADD_I8 =33,  ///< Add consts per channel with bytes
	ADD_I16=34, ///< Add consts per channel with halfwords
	LAYER_UNKNOWN=35
} layer_type_e;

/**
 * @brief Parameter to minor mode function
 */
typedef struct {
	//TODO: make this more generic for dense etc
	int maps,r,n,m,c,y;
    int total_input_channels;
	void* sp_in;
	void* sp_out;
	int32_t sp_bytes;
	int64_t graph_pointer;
} vnnx_layer_info_t;

struct vnnx_layer;
typedef int (*layer_run_func)(const struct vnnx_layer*,
                               vnnx_layer_info_t* /*inout*/);
/**
 * @brief Describes minor node in graph
 */

typedef STRUCT_PACKED vnnx_layer{
	int32_t type; //operator enum
	int32_t input_data_type;
	int32_t output_data_type;
	int32_t strides[2];
	int32_t kernel_shape[2];
	int32_t pads[6];
	int32_t maps;
	union{
		STRUCT_PACKED{
			float value;
		}pad_const;
		STRUCT_PACKED{
			float min;
			float max;
		}clip;
		STRUCT_PACKED{
			obj_off_t slope;
		}prelu;
		STRUCT_PACKED{
			int32_t alpha;
		}leakyrelu;
		STRUCT_PACKED{
			int32_t use_xl;
			float scalarf32;
			int32_t scalar32;
			int16_t scalar16;
			int8_t scalar8;
			uint8_t scalaru8;
		}mul_bc3;
		STRUCT_PACKED{
			int32_t use_xl;
			obj_off_t array;
			obj_off_t array_xl;
		}add_bc2;
		STRUCT_PACKED{
			int32_t use_xl;
			obj_off_t array;
			obj_off_t array_xl;
		}mul_bc2;
		STRUCT_PACKED{
		  int32_t scale;
		}cast;
		STRUCT_PACKED{
			int ceil_mode;
		}pool;
	};
} vnnx_layer_t;

struct vnnx_subgraph_node;
struct vnnx_graph;
typedef int (*subgraph_run_func)(const struct vnnx_graph* g,struct vnnx_subgraph_node*, const int cores, const int core_start, const int core_stop);

/**
 * @brief Describes major node in graph
 */
typedef STRUCT_PACKED vnnx_subgraph_node {
	int32_t type;
	int32_t input_data_type;
	int32_t output_data_type;
	int32_t input_unsigned;
	int32_t output_unsigned;
	int32_t input_size;
	int32_t output_size;
	int32_t output_strides[2];
	int32_t scratchpad_bytes;
	int32_t dma_channel_offset;
	int32_t dma_buffer_offset;

	obj_off_t input_data;
	obj_off_t output_data;
	char input_description[24];
	char output_description[24];
	obj_off_t test_input_data;
	obj_off_t test_output_data;
	obj_off_t sublayers;
	float output_scale_factor;
	int32_t num_sublayers;
	int32_t sublayer_stride;
	int32_t sublayer_shape;
	int32_t sublayer_shape_0;
	int32_t sublayer_shape_full;
	int32_t sublayer_shape_last;
	int32_t sublayer_rows;
	int32_t sublayer_columns;
	int32_t use_replay;
	obj_off_t replay_buffer;
	int32_t replay_buffer_size;
	int32_t output_shape[3];
	union {
		STRUCT_PACKED {
			int32_t fxp_scalar;
			int32_t bias_scalar;
			int32_t bias_lower_scalar;
			int32_t kernels;
			int32_t channels;
			int32_t kernel_shape[2];
			int32_t strides[2];
			int32_t dilations[2];
			int32_t group;
			int32_t m;
			int32_t n;
			int32_t padded_kernels;
			int32_t padded_channels;
			int32_t imaps;
			int32_t maps;
			int32_t acc_maps;
			int32_t rows;
			int32_t core_split;
			int32_t core_maps;
			int32_t core_m;
			int32_t use_weights32;
			int32_t use_cvi;
			int32_t use_depthwise;
			int32_t use_strided;
			float max_weight;
			obj_off_t weights;
			obj_off_t weights32;
			obj_off_t biases;
			obj_off_t biases_lower;
			obj_off_t scale;
		} conv;
		STRUCT_PACKED {
			int32_t channels;
			int32_t m;
			int32_t n;
			int32_t num_inputs;
			int32_t maps;
			int32_t rows;
		} sum;
		STRUCT_PACKED {
			int32_t channels;
			int32_t m;
			int32_t n;
            int32_t pixels_per_loop;
		} argmax;
		STRUCT_PACKED {
			int32_t channels;
			int32_t m;
			int32_t n;
			int32_t maps;
			int32_t core_split;
			int32_t core_maps;
			int32_t core_m;
			int32_t rows;
		} identity;
		STRUCT_PACKED {
			int32_t max_input_size;
			int32_t max_output_size;
			int32_t input_size;
			int32_t output_size;
			obj_off_t weights;
			obj_off_t biases;
		} gemm;
		STRUCT_PACKED{
			float alpha;
			float beta;
			float bias;
			float scale;
			int32_t size;
			int32_t channels;
			int32_t m;
			int32_t n;
			int32_t maps;
			int32_t rows;
		}lrn;
		STRUCT_PACKED{
			int32_t permutation[3];
            int32_t out_maps_at_once;
		}transpose;
		STRUCT_PACKED{
			float scale[2];
            int32_t mode;
			int32_t channels;
			int32_t m;
			int32_t n;
			int32_t maps;
			int32_t rows;
		}resize;
		STRUCT_PACKED{
			int32_t stride;
			int32_t channels;
			int32_t m;
			int32_t n;
			int32_t maps;
			int32_t rows;
		}reorg;
		STRUCT_PACKED{
			obj_off_t scale;
			int32_t size;
		}softmax;
	};
} vnnx_subgraph_node_t;

/**
 * @brief Description of communication interface between slave and host
 */

typedef STRUCT_PACKED {
	uint8_t is_master;

	uint32_t max_message_length;
  volatile uint8_t *send_base;
  volatile uint8_t *send_end;
  volatile uint32_t *send_write_offset_ptr;
  volatile uint32_t *send_read_offset_ptr;
  volatile uint8_t *recv_base;
  volatile uint8_t *recv_end;
  volatile uint32_t *recv_write_offset_ptr;
  volatile uint32_t *recv_read_offset_ptr;
} vbx_sm_comm_interface;

/**
 * @brief Description of core
 */
typedef struct{
	int is_host;
	vbx_sm_comm_interface comm;
}vnnx_core_t;


struct vnnx_shared_allocator;
/**
 * @defgroup vnnx Vectorblox ONNX Library.
 * @{
 */

/**
 * @brief Structure that describes how to allocate shared memory
 */
typedef struct vnnx_shared_allocator{
	void* (*alloc)(struct vnnx_shared_allocator*,size_t num_bytes);
	void (*free)(struct vnnx_shared_allocator*,void* ptr);
} vnnx_shared_allocator_t;

/**
 *  @brief External facing graph object
 */
typedef STRUCT_PACKED vnnx_graph{
	uint32_t version;
	uint32_t vbx_nn_preset;
	uint32_t num_inputs;
	uint32_t num_outputs;
	uint32_t data_bytes;
	uint32_t allocate_bytes;
	//after this the attributes are private
	obj_off_t io_nodes;
	int32_t num_layers;
	obj_off_t replay_buffer;
	int32_t replay_buffer_size;
	uint32_t magic;
	vnnx_subgraph_node_t subgraphs[0];
}vnnx_graph_t;

typedef enum {UNINITIALIZED, INVALID, VALID} recording_status_e;

/**
 * @brief Function pointer for running user kernels
 */

typedef int (*vnnx_user_kernel)(uint32_t core,
                                uint32_t cores,
                                uint32_t message_length,
                                uint8_t* message_buffer);

/**
 @}*/

#endif //VNNX_TYPES_H
