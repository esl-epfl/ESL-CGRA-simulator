#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "conv.h"



#if CHW_notHWC == 1

void __attribute__((optimize("O0")))conv2D()
{

  int32_t l, r, c, k, i, j, w, t;
  int32_t S;
  int32_t coeff;
  int32_t data;
  for (l = 0; l < N_output; l++)
  {
    for (k = 0; k < N_filter; k++)
    {
      for (r = 0; r < row_output; r++)
      {
        for (c = 0; c < col_output; c++)
        {
          S = 0;
          for (w = 0; w < C_filter; w++)
          {
            for (i = -FILT_HALF_x; i <= FILT_HALF_x; i++)
            {
              for (j = -FILT_HALF_y; j <= FILT_HALF_y; j++)
              {
                coeff = filter[k][w][i + FILT_HALF_x][j + FILT_HALF_y];

                data = input[l][w][r + i + FILT_HALF_x][c + j + FILT_HALF_y];
                S += coeff * data;
              }
            }
          }
          output[l][k][r][c] = S;
        }
      }
    }
  }






}
#elif CHW_notHWC == 0
void __attribute__((optimize("Ofast"))) conv2D()
{
  
  int32_t l, r, c, k, i, j, w, t;
  int32_t S;
  int32_t coeff;
  int32_t data;
  for (l = 0; l < N_output; l++)
  {
    for (k = 0; k < N_filter; k++)
    {
      for (r = 0; r < row_output; r++)
      {
        for (c = 0; c < col_output; c++)
        {
          S = 0;
          
            for (i = 0; i < row_filter; i++)
            {
              for (j = 0; j < col_filter; j++)
              {
                  for (w = 0; w < C_filter; w++)
                  {
                        data = input[l][r+i][c+j][w];
                        coeff = filter[k][i][j][w];
                        S+= coeff*data;

              }
            }

          }
          output[l][k][r][c] = S;
          

          
        }
      }
    }
  }





}
#endif







