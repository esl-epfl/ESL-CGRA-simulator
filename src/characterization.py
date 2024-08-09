import copy
import math
import os.path
import csv

OPERATIONS_MEMORY_ACCESS = ["LWD", "LWI", "SWD","SWI"]
BUS_TYPES = ["ONE-TO-M", "N-TO-M", "INTERLEAVED"]
INTERVAL_CST = 14

def load_operation_characterization(characterization_type, mapping_file='operation_characterization.csv'):
    operation_mapping = {}
    csv_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), mapping_file)
    with open(csv_file_path, 'r') as csvfile:
        reader = csv.reader(csvfile)
        current_section = None  
        for row in reader:
            if not row or row[0].startswith('#'):
                current_section = row[0].strip('# ') if row else current_section
                continue      
            if current_section == f'operation_{characterization_type}_mapping':
                operation, *rest = row         
                if len(rest) == 1:
                    key = int(rest[0])
                    operation_mapping[operation] = key
                elif len(rest) == 2:
                    key = int(rest[0])
                    value = float(rest[1])
                    if operation not in operation_mapping:
                        operation_mapping[operation] = {}
                    operation_mapping[operation][key] = value
    return operation_mapping

operation_latency_mapping = load_operation_characterization("latency_cc")
bus_type_active_row_coef = load_operation_characterization("active_row_coef")
bus_type_cpu_loop_instrs = load_operation_characterization("cpu_loop_instrs")

# This function takes the maximum latency between the memory operations and the non-memory operations in the instruction
def get_latency_cc(cgra):
    cgra.max_latency_instr = None
    longest_alu_op_latency_cc = get_latency_alu_cc(cgra)
    total_mem_latency_cc = get_latency_mem_cc(cgra)
    cgra.max_latency_instr.latency_cc = max(longest_alu_op_latency_cc, total_mem_latency_cc)
    if total_mem_latency_cc > longest_alu_op_latency_cc:
        cgra.max_latency_instr.instr = f'MEM ({cgra.max_latency_instr.instr})'  
    if (cgra.exit):
        cgra.max_latency_instr.latency_cc += 1      
    cgra.max_latency_instr.instr2exec = cgra.instr2exec    
    cgra.instr_latency_cc.append(copy.copy(cgra.max_latency_instr))
    cgra.total_latency_cc += cgra.instr_latency_cc[-1].latency_cc

def get_latency_alu_cc(cgra):
    for r in range(cgra.N_ROWS):
        for c in range(cgra.N_COLS):    
            cgra.cells[r][c].latency_cc = int(operation_latency_mapping[cgra.cells[r][c].op])                
            if cgra.max_latency_instr is None or cgra.cells[r][c].latency_cc > cgra.max_latency_instr.latency_cc:
                cgra.max_latency_instr = cgra.cells[r][c]     
    return cgra.max_latency_instr.latency_cc

def get_latency_mem_cc(cgra):
    record_bank_access(cgra)
    cgra.concurrent_accesses = group_dma_accesses(cgra)
    dependencies = track_dependencies(cgra)
    latency_cc = compute_latency_cc(cgra, dependencies)
    return latency_cc

# Record the bank index used for each memory access 
def record_bank_access(cgra):
    for r in range(cgra.N_ROWS):
        for c in range(cgra.N_COLS): 
            if cgra.cells[r][c].op in OPERATIONS_MEMORY_ACCESS:
                cgra.cells[r][c].bank_index = compute_bank_index(cgra,r,c)

def compute_bank_index(cgra, r, c):
    base_addr = cgra.init_store[0] if cgra.cells[r][c].op == "SWD" else sorted(cgra.memory)[0][0]  
    if cgra.memory_manager.bus_type == "INTERLEAVED":
        index_pos = int(((cgra.cells[r][c].addr - base_addr) / cgra.memory_manager.spacing) % cgra.memory_manager.n_banks)
    else:
        index_pos = cgra.cells[r][c].addr / cgra.memory_manager.bank_size
    return index_pos

def group_dma_accesses(cgra):
    # For each row, scan the PEs for memory accesses and place them into concurrent_accesses
    # If a column has no memory access, then scan all the rows on that column (=push up) 
    cgra.covered_accesses = []
    concurrent_accesses = [{} for _ in range(4)]
    for r in range(cgra.N_ROWS):
        for c in range(cgra.N_COLS):  
            if cgra.cells[r][c].op in OPERATIONS_MEMORY_ACCESS and (r, c) not in cgra.covered_accesses:
                cgra.covered_accesses, concurrent_accesses = mark_access(cgra.covered_accesses, concurrent_accesses, r, c, r, cgra.cells[r][c].bank_index)
            else:
                for k in range(cgra.N_ROWS):
                    if cgra.cells[k][c].op in OPERATIONS_MEMORY_ACCESS and (k, c) not in cgra.covered_accesses:
                        cgra.covered_accesses, concurrent_accesses = mark_access(cgra.covered_accesses, concurrent_accesses, r, c, k, cgra.cells[k][c].bank_index)
                        break
    if not accesses_are_ordered(cgra, concurrent_accesses):
        concurrent_accesses = rearrange_accesses(cgra, concurrent_accesses) 
    return concurrent_accesses

def mark_access(covered_accesses, concurrent_accesses, r, c, k, bank_index):
    # Record a PE and its bank index into concurrent_accesses 
    covered_accesses.append((k, c))
    concurrent_accesses[r].setdefault(bank_index, []).append((k, c))
    return covered_accesses, concurrent_accesses

def accesses_are_ordered(cgra, concurrent_accesses):
    if (cgra.memory_manager.bus_type != "INTERLEAVED"):
        return False
    else:
        highest_row = [0] * 4
        for i in range (cgra.N_ROWS):
            for values in concurrent_accesses[i].values():
                for current_access in values:
                    if highest_row[i] > current_access[0]:
                        return False
                    else:
                        highest_row[i] = current_access[0]
        return True

# This function arranges the concurrent lists to ensure they match the DMA's behavior
def rearrange_accesses(cgra, concurrent_accesses):
    if cgra.memory_manager.bus_type == "INTERLEAVED":
        for i in range(cgra.N_ROWS - 1, 0, -1):
            order_pairs = [pair[1] for pairs in concurrent_accesses[i].values() for pair in pairs][::-1]  
            concurrent_accesses[i-1] = {key: sorted(pairs, key=lambda x: order_pairs.index(x[1]) if x[1] in order_pairs else float('inf')) for key, pairs in concurrent_accesses[i-1].items()}
    else:
        # Latencies for non-interleaved bus types require the total number of accesses
        concurrent_accesses = [{1: [(0, 0)] * len(cgra.covered_accesses)}, {}, {}, {}]
    return concurrent_accesses

def track_dependencies(cgra):
    latency = [1] * 4 
    for i in range (cgra.N_ROWS):
        for values in cgra.concurrent_accesses[i].values():
            for current_access in values:
                # Compare each access with its next dependency (=subsequent access at same column)
                # Record the difference between the access within the conflict, and the subsequent access
                current_pos = find_position(cgra.concurrent_accesses[i], current_access[1]) + 1
                next_pos = find_position(cgra.concurrent_accesses[i+1], current_access[1]) if i < cgra.N_ROWS - 1 else 0
                latency[current_access[1]] += current_pos - next_pos
    return latency

def find_position(conflict_pos, column):
    for pairs in conflict_pos.items():
        for pair in pairs[1]:
            if pair[1] == column:
                return pairs[1].index(pair)
    return 0

def compute_latency_cc(cgra, dependencies):
    # Account for additional bus type specific delays
    ACTIVE_ROW_COEF =  bus_type_active_row_coef[cgra.memory_manager.bus_type]
    CPU_LOOP_INSTRS =  bus_type_cpu_loop_instrs[cgra.memory_manager.bus_type]
    mem_count = [0] * cgra.N_COLS
    latency_cc = max(dependencies)
    for r in range(cgra.N_ROWS):
        for c in range(cgra.N_COLS):                
            if cgra.cells[r][c].op in OPERATIONS_MEMORY_ACCESS:      
                mem_count[c] += 1
    if ACTIVE_ROW_COEF:
        for i in range (cgra.N_ROWS):
            if mem_count[i] != 0:
                latency_cc += ACTIVE_ROW_COEF
    if CPU_LOOP_INSTRS:
        cgra.flag_poll_cnt += latency_cc
        if cgra.flag_poll_cnt % (CPU_LOOP_INSTRS - 1) == 0:
            latency_cc += 1  
    return latency_cc

def display_characterization(cgra, pr):
    if any(item in pr for item in ["OP_MAX_LAT", "ALL_LAT_INFO"]):
        print("\nLongest instructions per cycle:\n")
        print("{:<8} {:<25} {:<10}".format("Cycle", "Instruction", "Latency (CC)"))
        for index, item in enumerate(cgra.instr_latency_cc):
            print("{:<2} {:<6} {:<25} {:<10}".format(index + 1, f'({item.instr2exec})', item.instr, item.latency_cc))
    if any(item in pr for item in ["TOTAL_LAT", "ALL_LAT_INFO"]):
        print(f'\nConfiguration time: {len(cgra.instrs)} CC')
        cgra.interval_latency = math.ceil(INTERVAL_CST + (len(cgra.instrs) * 3))
        print(f'Time between end of configuration and start of first iteration: {cgra.interval_latency} CC')
        print(f'Total time for all instructions: {cgra.total_latency_cc}')