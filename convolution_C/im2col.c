#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

// input parameters

#define H_inputs 16
#define W_inputs 16
#define C_inputs channels

// filter parameters

#define H_filter 5
#define W_filter 5
#define C_filter channels
#define FILT_HALF_x (H_filter / 2)
#define FILT_HALF_y (W_filter / 2)

// output parameters

#define N_outputs batch_size
#define H_outputs (((H_inputs + 2 * padding - H_filter) / stride) + 1)
#define W_outputs (((W_inputs + 2 * padding - W_filter) / stride) + 1)
#define channels_outputs N_filters

// im2col parameters

#define H_im2col (H_filter * W_filter * C_filter)
#define W_im2col (H_outputs * W_outputs)

// general parameters

#define stride 1
#define padding 0
#define N_filters 1
#define channels 1
#define batch_size 1

// filter 4d 1 channel
static int32_t filter[N_filters][C_filter][H_filter][W_filter] =
    {
        {{{1, 2, 3, 4, 5},
          {4, 5, 6, 7, 8},
          {7, 8, 9, 1, 2},
          {10, 11, 12, 13, 14},
          {13, 14, 15, 16, 17}}}};

// 4d input 1 channel
static int32_t inputs[batch_size][C_inputs][H_inputs][W_inputs] =
    {{{{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15},
       {16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31},
       {32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47},
       {48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63},
       {64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79},
       {80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95},
       {96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111},
       {112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127},
       {128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139 ,140, 141, 142, 143},
       {144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155 ,156, 157, 158, 159},
       {160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171 ,172, 173, 174, 175},
       {176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187 ,188, 189, 190, 191},
       {192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207},
       {208, 209, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 221, 222, 223}, 
       {224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239},
       {240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 250, 251, 252, 253, 254, 255}

    }}};

// inputs 4d 3 channels
// static int32_t inputs[batch_size][C_inputs][H_inputs][W_inputs] =
//{
//{
//    {{1, 2, 3, 4, 5, 6},
//     {2, 3, 4, 5, 6, 7},
//     {3, 4, 5, 6, 7, 8},
//     {4, 5, 6, 7, 8, 9},
//     {5, 6, 7, 8, 9, 10},
//     {6, 7, 8, 9, 10, 11}},
//     {
//      {1, 2, 3, 4, 5, 6},
//     {2, 3, 4, 5, 6, 7},
//     {3, 4, 5, 6, 7, 8},
//     {4, 5, 6, 7, 8, 9},
//     {5, 6, 7, 8, 9, 10},
//     {6, 7, 8, 9, 10, 11}},
//     {
//      {1, 2, 3, 4, 5, 6},
//     {2, 3, 4, 5, 6, 7},
//     {3, 4, 5, 6, 7, 8},
//     {4, 5, 6, 7, 8, 9},
//     {5, 6, 7, 8, 9, 10},
//     {6, 7, 8, 9, 10, 11}
//     }
//
//
//
//}
//};
static int32_t in2col_mat[batch_size][H_im2col][W_im2col];
static int32_t in2col_vett[N_filters][H_filter * W_filter * C_filter];

// filter 4d 3 channels
// static int32_t filter[N_filters][C_filter][H_filter][W_filter]=
//
//{
//
//   {
//    {
//     {1, 2, 3 ,4, 5},
//      {4, 5, 6 ,7, 8},
//      {7, 8, 9 , 1, 2},
//      {10, 11, 12, 13, 14},
//        {13, 14, 15, 16, 17}
//     },
//     {
//      {2, 3, 4, 5, 6},
//      {5, 6, 7, 8, 9},
//      {8, 9, 1, 2, 3},
//      {11, 12, 13, 14, 15},
//      {14, 15, 16, 17, 18}
//     },
//     {
//      {3, 4, 5, 6, 7},
//      {6, 7, 8, 9, 1},
//      {9, 1,2, 3, 4},
//      {12, 13, 14, 15, 16},
//      {15, 16, 17, 18, 19}
//      }
//      }
//
//   };

int main()
{

  int i, j, k, l, c, m, n, o, p, q, r, s, t, u, v, w;

  for (l = 0; l < batch_size; l++)
  {
    for (k = 0; k < N_filters; k++)
    {
      for (m = 0; m < H_outputs; m++)
      {
        for (n = 0; n < W_outputs; n++)
        {

          for (w = 0; w < C_filter; w++)
          {
            for (i = -FILT_HALF_x; i <= FILT_HALF_x; i++)
            {
              for (j = -FILT_HALF_y; j <= FILT_HALF_y; j++)
              {

                int dato_selezionato = inputs[l][w][m + i + FILT_HALF_x][n + j + FILT_HALF_y];

                int posto_input = (W_filter) * (i + 2) + (j + 2) + w * (H_filter * W_filter);
                in2col_vett[k][(W_filter) * (i + 2) + (j + 2) + w * (H_filter * W_filter)] = filter[k][w][i + FILT_HALF_x][j + FILT_HALF_y];
                in2col_mat[l][(W_filter) * (i + 2) + (j + 2) + w * (H_filter * W_filter)][n + (H_outputs * m)] = inputs[l][w][m + i + FILT_HALF_x][n + j + FILT_HALF_y];
              }
            }
          }
        }
      }
    }
  }

printf("in2col_vett\n");
for (int i = 0; i< N_filters; i++){
  for (int j = 0; j< W_im2col; j++){
    for (int k = 0; k<H_im2col; k++){
      printf("%d ", in2col_mat[i][k][j]);

    }
    printf("\n");
  }
  printf("\n\n");
}
  return 0;
}