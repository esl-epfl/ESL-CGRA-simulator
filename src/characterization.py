import copy
import math
import os.path
import csv
import re

OPERATIONS_MEMORY_ACCESS = ["LWD", "LWI", "SWD","SWI"]
BUS_TYPES = ["ONE-TO-M", "N-TO-M", "INTERLEAVED"]
IDENTICAL_INSTR_CST = 25
CLK_PERIOD  = 12.5E-09 # 12.5 ns 
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
operation_power_mapping = load_operation_characterization("power_w")
operation_passive_power_mapping = load_operation_characterization("passive_power_w")
operation_clk_gate_mapping = load_operation_characterization("clk_gate_power_w")

# This function takes the maximum latency between the memory operations and the non-memory operations in the instruction
def get_latency_cc(cgra):
    cgra.max_latency_instr = None
    longest_alu_op_latency_cc = get_latency_alu_cc(cgra)
    total_mem_latency_cc = get_latency_mem_cc(cgra)
    cgra.max_latency_instr.latency_cc = max(longest_alu_op_latency_cc, total_mem_latency_cc)
    if total_mem_latency_cc > longest_alu_op_latency_cc:
        cgra.max_latency_instr.instr = f'MEM ({cgra.max_latency_instr.instr})'
    if (cgra.exit and cgra.max_latency_instr.instr != "EXIT"):
        cgra.max_latency_instr.latency_cc += 1
    cgra.max_latency_instr.instr2exec = cgra.instr2exec
    cgra.instr_latency_cc.append(copy.copy(cgra.max_latency_instr))
    cgra.total_latency_cc += cgra.instr_latency_cc[-1].latency_cc

def get_latency_alu_cc(cgra):
    for r in range(cgra.N_ROWS):
        for c in range(cgra.N_COLS):
            cgra.cells[r][c].latency_cc = int(operation_latency_mapping[cgra.cells[r][c].op])                
            if cgra.max_latency_instr is None or cgra.cells[r][c].latency_cc > cgra.max_latency_instr.latency_cc:
                cgra.max_latency_instr = copy.copy(cgra.cells[r][c])
    return cgra.max_latency_instr.latency_cc

def get_latency_mem_cc(cgra):
    record_bank_access(cgra)
    cgra.concurrent_accesses = group_dma_accesses(cgra)
    dependencies = track_dependencies(cgra)
    latency_cc = get_total_memory_access_cc(cgra, dependencies)
    return latency_cc

# Record the bank index used for each memory access 
def record_bank_access(cgra):
    for r in range(cgra.N_ROWS):
        for c in range(cgra.N_COLS): 
            if cgra.cells[r][c].op in OPERATIONS_MEMORY_ACCESS:
                cgra.cells[r][c].bank_index = compute_bank_index(cgra,r,c)

def compute_bank_index(cgra, r, c):
    if (cgra.memory):
        base_addr = cgra.init_store[0] if cgra.cells[r][c].op == "SWD" else sorted(cgra.memory)[0][0]  
    if cgra.memory_manager.bus_type == "INTERLEAVED":
        index_pos = int(((cgra.cells[r][c].addr - base_addr) / cgra.memory_manager.word_size_B) % cgra.memory_manager.banks_n)
    elif cgra.memory_manager.bus_type == "N-TO-M":
        index_pos = cgra.cells[r][c].addr / cgra.memory_manager.bank_size_B
    else:
        index_pos = 1
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
def rearrange_accesses(cgra, concurrent_accesses) :
    if cgra.memory_manager.bus_type == "INTERLEAVED":
        for i in range(cgra.N_ROWS - 1, 0, -1):
            order_pairs = [pair[1] for pairs in concurrent_accesses[i].values() for pair in pairs][::-1]
            concurrent_accesses[i-1] = {key: sorted(pairs, key=lambda x: order_pairs.index(x[1]) if x[1] in order_pairs else float('inf'))
                    for key, pairs in concurrent_accesses[i-1].items()}
    else:
         # Latencies for non-interleaved bus types require the total number of accesses 
        concurrent_accesses = [{1: [(0, 0)] * len(cgra.covered_accesses)}, {}, {}, {}]
    return concurrent_accesses

def track_dependencies(cgra): 
    latency = [1] * 4 
    # Iterate over each sequence (= flattened row), examining them two-by-two:
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

def get_total_memory_access_cc(cgra, dependencies):
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

def get_power_w(cgra):
    cgra.power.append([[0 for _ in range(cgra.N_COLS)] for _ in range(cgra.N_ROWS)])
    cgra.energy.append([[0 for _ in range(cgra.N_COLS)] for _ in range(cgra.N_ROWS)])
    for r in range(cgra.N_ROWS):
        for c in range(cgra.N_COLS):
            get_cell_power_w(cgra.cells[r][c], cgra.max_latency_instr.latency_cc)              
            cgra.power[-1][r][c] = cgra.cells[r][c].power
            get_cell_energy_j(cgra.cells[r][c], cgra.max_latency_instr.latency_cc)
            cgra.energy[-1][r][c] = cgra.cells[r][c].energy
        if (cgra.cycles > 1):
            if (cgra.power[-1] == cgra.power[-2]): 
                cgra.identical_instr += 1  
    if (cgra.exit):
        cgra.avg_pwr_array = [[0 for _ in range(cgra.N_COLS)] for _ in range(cgra.N_ROWS)]
        cgra.energy_array = [[0 for _ in range(cgra.N_COLS)] for _ in range(cgra.N_ROWS)]
        for index, item in enumerate(cgra.instr_latency_cc):     
            for row_idx in range(cgra.N_ROWS):
                for col_idx in range(cgra.N_COLS):
                    cgra.avg_pwr_array[row_idx][col_idx] += (cgra.power[index][row_idx][col_idx] * item.latency_cc)
                    cgra.energy_array[row_idx][col_idx] += cgra.energy[index][row_idx][col_idx]
        cgra.avg_pwr_array = [[value / cgra.total_latency_cc for value in row] for row in cgra.avg_pwr_array]
        cgra.avg_pwr = sum([power for row in cgra.avg_pwr_array for power in row])
        cgra.avg_energy = sum([energy for row in cgra.energy_array for energy in row])
        if cgra.identical_instr < IDENTICAL_INSTR_CST:
            cgra.avg_pwr += 1.00E-4

def get_cell_power_w(cell, latency):  
    if cell.op in operation_power_mapping:
        if cell.op in cell.ops_arith:
            handle_alu(cell)            
        average_pwr = fetch_operation_value(cell, cell.op, latency, "power")
        active_pwr = fetch_operation_value(cell, cell.op, cell.latency_cc, "power")
        cell.power = average_pwr
        if (fetch_operation_value(cell, cell.op,latency, "passive") != 0 ):             
            cell.active_energy = active_pwr * cell.latency_cc 
            cell.passive_energy = fetch_operation_value(cell, cell.op,latency, "passive") * ( latency - cell.latency_cc)
            cell.power = (cell.active_energy + cell.passive_energy) / latency      
        if cell.op == 'NOP' or cell.op == 'EXIT':
            cell.power += fetch_operation_value(cell, "CLK_IDLE", latency, "clk") 
        else:
            cell.power += fetch_operation_value(cell, "CLK_ACTIVE", latency, "clk") 

def get_cell_energy_j(cell, latency):  
    if cell.op in operation_power_mapping:
        cell.energy = cell.power * latency

def handle_alu(cell):
        from cgra import regs
        pattern_r_digit = re.compile(r"r[0-3]", re.IGNORECASE)
        pattern_rc_letter = re.compile(r"rc[b-lrt]", re.IGNORECASE)
        pattern_numeric = re.compile(r"\b\d+\b")
        matches = [elem.strip() for elem in re.split(r'[ ,]+', cell.instr)[1:]]
        matches_str = ' '.join(matches)
        int_reg_cnt = len(pattern_r_digit.findall(matches_str))
        ext_reg_cnt = len(pattern_rc_letter.findall(matches_str))
        cst_cnt = len(pattern_numeric.findall(matches_str))
        if cell.out == 0:
            cell.params_info = "X0"
        if cell.op == 'SMUL' or cell.op == 'FXPMUL': 
            for match in pattern_r_digit.findall(cell.op[1:]):
                digit = int(match[1])
                if cell.regs[regs[digit]] == 1 or cell.regs[regs[digit]] == 2:
                    cell.params_info = f'X{cell.regs[regs[digit]]}'
        if cell.op == 'SMUL' or cell.op == 'SADD': 
            if ext_reg_cnt >= 1:
                cell.params_info = "EXT"
            elif int_reg_cnt == 2 and cst_cnt == 1:
                cell.params_info = "CST" 
            elif int_reg_cnt == 3:
                cell.params_info = "INT"

def fetch_operation_value(cell, op, latency, type):
    def get_value(mapping, op_key, latency):
        return mapping[op_key].get(latency, mapping[op_key].get(cell.latency_cc, 0))
    if type == "power":
        op_key = f"{op}_{cell.params_info}" if (f"{op}_{cell.params_info}") in operation_power_mapping else op
        if op_key in operation_power_mapping:
            return get_value(operation_power_mapping, op_key, latency)    
    elif type == "passive":
        op_key = f"{op}_{cell.params_info}" if cell.params_info else op
        if op_key in operation_passive_power_mapping:
            return get_value(operation_passive_power_mapping, op_key, latency)
        else:
            return 0    
    elif type == "clk":
        return operation_clk_gate_mapping.get(op, {}).get(latency, 0)
    return 0

def display_characterization(cgra, pr):
    if any(item in pr for item in ["OP_MAX_LAT", "ALL_LAT_INFO"]):
        print("\nLongest instructions per cycle:\n")
        print("{:<8} {:<25} {:<10}".format("Cycle", "Instruction", "Latency (CC)"))
        for index, item in enumerate(cgra.instr_latency_cc):
            print("{:<2} {:<6} {:<25} {:<10}".format(index + 1, f'({item.instr2exec})', item.instr, item.latency_cc))
    if any(item in pr for item in ["TOTAL_LAT", "ALL_LAT_INFO"]):
        cgra.interval_latency = math.ceil(INTERVAL_CST + (len(cgra.instrs) * 3))
        print(f'\nConfiguration time: {len(cgra.instrs)} CC\nTime between end of configuration and start of first iteration: {math.ceil(14 + (len(cgra.instrs) * 3))} CC\nTotal time for all instructions: {cgra.total_latency_cc}') 
    if any(item in pr for item in ["AVG_OP_PWR_INFO", "ALL_PWR_EN_INFO"]):
        print("\nAverage power per operation:\n")
        out_string = ""
        for r in range(cgra.N_ROWS):
            out_string += "["
            for i in range(len(cgra.avg_pwr_array[r])):
                out_string += "{{{}:.2e}}".format(i)
                if i == (len(cgra.avg_pwr_array[r]) - 1):
                    out_string += "]\n"
                else:
                    out_string += ", "
            out_string = out_string.format(*[o for o in cgra.avg_pwr_array[r]])
        print(out_string)
    if any(item in pr for item in ["AVG_INSTR_PWR_INFO", "ALL_PWR_EN_INFO"]):
        print("\nPower estimation for all instructions:", format(cgra.avg_pwr, ".2e"), " W")
    if any(item in pr for item in ["AVG_INSTR_EN_INFO", "ALL_PWR_EN_INFO"]):
        print("\nTotal energy consumed:", format(cgra.avg_energy * CLK_PERIOD, ".2e"), "J")
        print("\nClock period used:", CLK_PERIOD, "s")