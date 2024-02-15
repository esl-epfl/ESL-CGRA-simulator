/*
                              *******************
******************************* H HEADER FILE *******************************
**                            *******************                          **
**                                                                         **
** project  : CGRA-X-HEEP                                                  **
** filename : conv.h                                                   **
** version  : 1                                                            **
** date     : 2023-08-28                                                    **
**                                                                         **
*****************************************************************************
**                                                                         **
** Copyright (c) EPFL                                                      **
** All rights reserved.                                                    **
**                                                                         **
*****************************************************************************
*/

/***************************************************************************/
/***************************************************************************/

/**
* @file   conv.h
* @date   2023-08-28
* @brief  A description of the kernel...
*
*/

#ifndef _CONVOLUTION_H_
#define _CONVOLUTION_H_

/****************************************************************************/
/**                                                                        **/
/**                            MODULES USED                                **/
/**                                                                        **/
/****************************************************************************/

#include <stdint.h>
#include "../../kernels_common/kernels_common.h"
extern kcom_kernel_t conv_kernel;
// general parameters

#define stride 1
#define padding 0
#define N_filter ${output_channel}
#define channel ${input_channel}
#define batch_size 1
# define CHW_notHWC 0
// input parameters

#define row_input ${input_dim}
#define col_input ${input_dim}
#define C_input channel

// filter parameters

#define row_filter 3
#define col_filter 3
#define C_filter channel
#define FILT_HALF_x (row_filter / 2)
#define FILT_HALF_y (col_filter / 2)

// output parameters
#define N_output batch_size
#define row_output (((row_input + 2 * padding - row_filter) / stride) + 1)
#define col_output (((col_input + 2 * padding - col_filter) / stride) + 1)
#define channel_output N_filter

/*input 16x16x16*/
static int32_t input[batch_size][C_input][row_input][col_input]=
{{
% for i in range(0, input_channel):
    {
% for j in range(0, input_dim):
        {
%for k in range(0, input_dim):
            ${k + j*input_dim}${"," if k != input_dim-1 else ""}
% endfor
        }${"," if j != input_dim-1 else ""}
% endfor
    }${"," if i != input_channel-1 else ""}
% endfor
}};


static int32_t filter[N_filter][C_filter][row_filter][col_filter]=

{
% for i in range(0, output_channel):
    {
% for j in range(0, input_channel):
        {
% for k in range(0, 3):
            {
% for l in range(0, 3):
                  ${1+l + k*3}${"," if l != 3-1 else ""}
% endfor     
            }${"," if k != 3-1 else ""}
% endfor
        }${"," if j != input_channel-1 else ""}
% endfor
    }${"," if i != output_channel-1 else ""}
% endfor
};




   





static int32_t output[N_output][channel_output][row_output][col_output];
/****************************************************************************/
/**                                                                        **/
/**                          EXPORTED VARIABLES                            **/
/**                                                                        **/
/****************************************************************************/



#endif // _REVERSEBITS_H_
/****************************************************************************/
/**                                                                        **/
/**                                EOF                                     **/
/**                                                                        **/
/****************************************************************************/