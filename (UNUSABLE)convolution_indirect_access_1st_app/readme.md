### 14<sup>th<sup> November
This folder contains the assembly instruction for a convolution with: 16x16 as input and 3x3 as filter. This assembly code
should be the basic version of one more optimized. The reasoning is the following: we should implement a convolution with
16x16x16 as input and 16x16x3x3 as filter: so the CGRA is called every 16 cycles (representing the number of input channel),
and again this inner loop is called again 16 times (representing the number of output channel). 
Here the problem is I need 38 instructions in order to:
1. **load indirect the input and the filter**
2. **handle offset to point other input and filter**

