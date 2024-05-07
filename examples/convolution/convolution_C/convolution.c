#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "convolution.h"

int main()
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
          outputs[l][k][r][c] = S;
        }
      }
    }
  }
  printf("Output:\n");
  for (l = 0; l < N_output; l++)
  {
    for (k = 0; k < N_filter; k++)
    {
      for (r = 0; r < row_output; r++)
      {
        for (c = 0; c < col_output; c++)
        {
          printf("%d ", outputs[l][k][r][c]);
        }
        printf("\n");
      }
      printf("\n");
    }
    printf("\n");
  }

  return 0;
}
