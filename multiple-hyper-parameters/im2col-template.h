#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "conv.h"
// im2col parameters

#define col_im2col (row_filter * col_filter * C_filter)
#define row_im2col (row_output * col_output)




void __attribute__((optimize("Os"))) im2col_conv(int32_t *input_to_CGRA, int32_t *filter_to_CGRA, int out_row, int out_col, int output_channel)
{

  int i, j, k, l, c, m, n, o, p, q, r, s, t, u, v, w;


for (i = 0; i < row_filter; i++)
      {

%for j in range(3):
%for k in range(input_channel):
input_to_CGRA[${k} + C_filter * ${j} + C_filter * col_filter*i] = input[0][i+out_row][${j}+out_col][${k}];
%endfor
%endfor



                  
            
          }

        }
      
    
  









