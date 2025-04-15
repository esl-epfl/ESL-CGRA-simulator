# Latency
The simulator features an estimation tool that provides latency results for each instruction.

To do so, an algorithm returns the maximum value between the longest ALU (non-memory) operation and the total latency due to memory accesses.

### Instruction-level breakdown
* ALU operation latencies are straightforward to compute, as they all take 1 CC to execute, with the exception of multiplications (SMUL and FXPMUL) which take 3 CCs. 
* To compute the total latency of the memory operations (LWD, SWD, LWI, and SWI), the simulator must consider the bus type (default: one-to-M).
* In the case where the instruction contains an “EXIT” operation, 1 CC is added to the final latency.
### Printing results
* Finally, to select the output information to display, users must pass one or more of the following strings to the pr string array:
    * `OP_MAX_LAT`: prints the longest operation for each instruction. If the longest operation is a memory access, the resulting output will be “MEM” followed by the operation’s name in parentheses.
    * `TOTAL_LAT`: only displays the configuration time, the time between end of configuration and start of first iteration, and the total time for all instructions.
    * `ALL_LAT_INFO`: prints all latency information.

### Parametrization
To specify a different bus type (one-to-M, N-to-M, or interleaved), users must instantiate `Memory` class with the desired parameter, and pass this class to the CGRA’s `run` function like so:


```python
python memory_manager = MEMORY("INTERLEAVED")
run(kernel_name, pr=["ROUT","OPS", "ALL_LAT_INFO","ALL_PWR_EN_INFO"], load_addrs=load_addrs, store_addrs=store_addrs, limit = 300, memory_manager=memory_manager)
```

The estimator can be further parametrized by directly modifying the `operation_characterization.csv` file, from which per-operation latencies and bus type specificities are fetched.

# Power/Energy

The simulator also generates an estimation for power and energy consumption, computing values at different levels of abstraction:

* Total power across all instructions: Average of the total power used by each instruction.
* Average power per PE: The average power consumption of each PE throughout the entire execution.
* Total power per instruction: Sum of the power used by all PEs for an instruction.
* PE power per instruction: Power consumed by a PE during an instruction.

### Instruction-level breakdown

* The algorithm retrieves the power values for each operation type from the `operation_characterization.csv` file. 
* In addition to the operation type, the estimator also considers an operation’s parameters (internal or external register, immediate) as well as the output computed (ex: multiplying by 0, 1, or 2). 

### Printing results
* Finally, to select the output information to display, users must pass one or more of the following strings to the pr string array:
    * `PWR_OP / EN_OP`: displays the average power/energy for each operation, as well as a total value per instruction.
    * `AVG_INSTR_PWR_INFO / AVG_INSTR_EN_INFO`: only displays the average power/energy for all instructions.
    * `ALL_PWR_EN_INFO`: prints all power and energy information.

### Parametrization

Once again, users can further parametrize the estimator by specifying their own per-operation values in the mapping file. 






