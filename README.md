# ESL-CGRA Simulator
This notebook allows you to manage kernels, simulate them and generate assembly files that can the be integrated into the CGRA-X-HEEP flow.
This simulator does not include the compilation of C code into CGRA-compatible assembly code. For that purpose refer to [SAT-MapIt](https://github.com/CristianTirelli/SAT-MapIt).

# Structure
It is divided into 3 main components:

### Utility files
Include the simulator per se and a set of tools to simplify the process of generating, debugging and exporting the results.

### Kernel folders
A kernel is a section of an application that wants to be accelerated in the CGRA.
Each kernel has a folder with its name. All the files needed to run a simulation should be inside them and follow the naming convention detailed in [Creating a kernel](#creating-a-kernel). These include (but are not restricted to):
* (optional) A file containing the `SAT-MapIt` output.
* (optional) A hand-written assembly file.
* (optional) A `memory.csv` file including the indexed values that the kernel can access from memory.

    You can either write this file by hand or fill the memory using the `kernel_add_memory_region` function. 
* A `instructions.csv` file containing a matrix of operations to be executed by each Processing Element (PE) during each instruction.

    This file can be automatically generated from a `.out` file or hand-written assembly. 
* A `memory_out.csv` file is generated after every run of the simulator. This file is overriden, so save it somewhere else if you want to keep track of it.

You may have more than one version of the instructions and memory files (all named `instructions<version>.csv` or `memory<version>.csv` (replacing `<version>` with any string).


### Notebook
An `simulator.ipynb` is provided to play with the different functionalities of the simulator. You can run actions and see the output directly there. Also, a separate notebook for each example is provided.

# Usage
The usage of the simulator throught the notebook is very straight-forward.

## Creating a kernel
Creating a kernel involves creating a folder with its name and populating it with the necessary files. The module `kernels` provide some functions to assist in this task.

### Folder
To generate a new folder and fill it with empty `memory` file call.
```python
kernel_new("<kernel_name>")
```

### Memory
The memory can be easily populated with some patter by calling the function
```python
kernel_add_memory_region( "<kernel_name>", <address>, <array_of_values>, [<version>])
```

The `memory.csv` file should always have this format

| Address | Data |
| --- | --- |
| `<address 0>` | `<data 0>` |
| `<address 1>` | `<data 1>` |
| . . . | . . . |

Address values do not need to be ordered. When the kernel tries to access a certain address, it will go through the table until it finds it, then return the corresponding data.
If the address is not found, `-1` is returned (simulating a flash read from an empty address).

When storing information, the kernel will look for the address specified and write in the corresponding data space the value given. If the address is not found, a new line is created containing it.

When using the `kernel_add_memory_region` function, overlaps are not considered (i.e. a same memory address might appear more than once in the table, but only the first one will be considered by the simulator -as it will always be found first). Be careful.

### Instructions

Instruction files can be generated automatically from the output of `SAT-MapIt` or a manually-written assembly file following the same structure, or can be created manually editing the `.csv` file.

It should has the same number of columns as the CGRA and only as many rows as instructions + the header of each instruction.

Each instruction is composed as follows (for a $2 \times 2$ CGRA):

| `<instr. number>` | |
| --- | --- |
| `<op. for PE 00>` |`<op. for PE 01>` |
| `<op. for PE 10>` |`<op. for PE 11>` |

Notes:
* Always place only the instruction number only in the first column.
* Do not leave empty rows (not even at the end of the file).


The instructions file can be modified to play around with the kernel. If different options want to be considered, the instructions file can be given a version as `instruction<version>.csv`. For different versions of the instructions file you will also need a different version of the memory file, given as `memory<version>.csv`.
When requesting the execution of a kernel, provide the name of the kernel and (optionally) the desired version.


## Changing the CGRA size

Currently the CGRA size is hardcoded in the `cgra.py` module. You can change this value to whatever dimensions you want, even non squared.

Providing functionality to change this from the notebook interface should be pretty straightforward. If you feel generous today, please open a pull request :)


## Running a kernel

Once the whole kernel folder has been filled, you can simply run a simulation by calling the `run` function of the `cgra` module.
```python
import cgra
cgra.run("<kernel_name>")
```


### Temporal record
In the output of the notebook a step by step state of each PE's output register is printed until an `EXIT` instruction is reached. If this instruction was not added, you might very well want to cancel the execution.

Each instruction is divided by dashes and headed by the step number and the instruction being executed (the one found in the `instructions` file):
```
Instr = <step number> (<instruction number>)
```
Each PE in the matrix shows (by default) the value of `ROUT` after each iteration. For example:
```
Instr =  8 ( 3 )
[   0,    0,    0,    0]
[   2,    2,    2,    0]
[   3,    3,    3,    0]
[   0,    0,    0,    0]
```

What is shown in each cell can be modified when calling the `run` function. For instance calling the function as follows will output the value of `R0` instead of `ROUT` for the kernel `convolution` in its version `_v2` (i.e. will run the instructions from the file `convolution/instructions_v2.csv`).
```python
run("convolution", version="_v2", pr=["ROUT", "OPS"])
```

Optional `pr` parameters include:
| Parameter | Description |
| --- | --- |
| `ROUT` (default) | The output register of the PE|
| `R0` - `R3` | One of the 4 available registers of each P|
| `INST` | The full instruction that the cell is executing|
| `OPS`  | The name of the operation that the cell is executing|
| `[<p1>, <p2>]` | An array with any amount of the above parameters |

### Output

Outputs written using the `SWD` or `SWI` operations are written into a `memory_out.csv` file, so the `memory.csv` file is untouched for future executions. The `memory_out.csv` file is overriden on every run.


# Additional notes

* If you make any modification to the utility scripts, you might need to restart the notebook for the changes to apply.