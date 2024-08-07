import copy
import math
import os.path
import csv

OPERATIONS_MEMORY_ACCESS = ["LWD", "LWI", "SWD","SWI"]
BUS_TYPES = ["ONE-TO-M", "N-TO-M", "INTERLEAVED"]

def load_operation_characterization(characterization_type):
    operation_mapping = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_file_path = os.path.join(script_dir, 'operation_characterization.csv')
    with open(csv_file_path, 'r') as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            if not row:
                continue
            if row[0].startswith('#'):
                current_section = row[0].strip('# ')
                continue
            if current_section == f'operation_{characterization_type}_mapping':
                if len(row) == 3:
                    key_type, value_type = int, float
                    operation, key, value = row
                    key = key_type(key)
                    value = value_type(value)
                    if operation not in operation_mapping:
                        operation_mapping[operation] = {}
                    operation_mapping[operation][key] = value
                elif len(row) == 2:
                        key_type, value_type = int, int
                        operation, key = row
                        key = key_type(key)
                        if operation not in operation_mapping:
                            operation_mapping[operation] = key
            else:
                continue 
    return operation_mapping

operation_latency_mapping = load_operation_characterization("latency_cc")
bus_type_active_row_coef = load_operation_characterization("active_row_coef")
bus_type_cpu_loop_instrs = load_operation_characterization("cpu_loop_instrs")

def get_latency_cc(self):
    self.max_latency_instr = None
    longest_alu_op_latency_cc = get_latency_alu_cc(self)
    total_mem_latency_cc = get_latency_mem_cc(self)
    self.max_latency_instr.latency_cc = max(longest_alu_op_latency_cc, total_mem_latency_cc)
    if total_mem_latency_cc > longest_alu_op_latency_cc:
        self.max_latency_instr.instr = f'MEM ({self.max_latency_instr.instr})'  
    if (self.exit):
        self.max_latency_instr.latency_cc += 1      
    self.max_latency_instr.instr2exec = self.instr2exec    
    self.instr_latency_cc.append(copy.copy(self.max_latency_instr))
    self.total_latency_cc += self.instr_latency_cc[-1].latency_cc

def get_latency_alu_cc(self):
    from cgra import N_ROWS, N_COLS
    for r in range(N_ROWS):
        for c in range(N_COLS):    
            self.cells[r][c].latency_cc = int(operation_latency_mapping[self.cells[r][c].op])                
            if self.max_latency_instr is None or self.cells[r][c].latency_cc > self.max_latency_instr.latency_cc:
                self.max_latency_instr = self.cells[r][c]     
    return self.max_latency_instr.latency_cc

def get_latency_mem_cc(self):
    record_bank_access(self)
    self.concurrent_accesses = group_dma_accesses(self)
    dependencies = track_dependencies(self)
    latency_cc = compute_latency_cc(self, dependencies)
    return latency_cc

def record_bank_access(self):
    from cgra import N_ROWS, N_COLS
    for r in range(N_ROWS):
        for c in range(N_COLS): 
            if self.cells[r][c].op in OPERATIONS_MEMORY_ACCESS:
                self.cells[r][c].bank_index = compute_bank_index(self,r,c)

def compute_bank_index(self, r, c) :
    if self.bus_type == "INTERLEAVED":
        if self.cells[r][c].op == "SWD":
            index_pos = int(((self.cells[r][c].addr - self.init_store[0]) / 4) % 8)
        else:
            index_pos = int(((self.cells[r][c].addr - sorted(self.memory)[0][0]) / 4) % 8)
    elif self.bus_type == "N-TO-M":
        index_pos = 1
    elif self.bus_type == "ONE-TO-M":
        index_pos = 1
    return index_pos

def group_dma_accesses(self):
    from cgra import N_ROWS, N_COLS
    covered_accesses = []
    concurrent_accesses = [{} for _ in range(4)]
    # reorder memory accesses to group into concurrent executions
    # covered_accesses tracks the accesses that have already been visited
    for r in range(N_ROWS):
        for c in range(N_COLS):  
            if self.cells[r][c].op in OPERATIONS_MEMORY_ACCESS and (r, c) not in covered_accesses:
                covered_accesses, concurrent_accesses = update_accesses(covered_accesses, concurrent_accesses, r, c, r, self.cells[r][c].bank_index)
            else:
                for k in range(N_ROWS):
                    if self.cells[k][c].op in OPERATIONS_MEMORY_ACCESS and (k, c) not in covered_accesses:
                        covered_accesses, concurrent_accesses = update_accesses(covered_accesses, concurrent_accesses, r, c, k, self.cells[k][c].bank_index)
                        break
    if self.bus_type != "INTERLEAVED":
        concurrent_accesses = [{1: [(0, 0)] * len(covered_accesses)}, {}, {}, {}]
    elif not accesses_are_ordered(concurrent_accesses):
        for i in range(N_ROWS - 1, 0, -1):
            concurrent_accesses[i-1] = rearrange_accesses(concurrent_accesses[i-1], concurrent_accesses[i]) 
    return concurrent_accesses

def update_accesses(covered_accesses, concurrent_accesses, r, c, k, bank_index):
    covered_accesses.append((k, c))
    if bank_index not in concurrent_accesses[r]:
        concurrent_accesses[r][bank_index] = []
    concurrent_accesses[r][bank_index].append((k, c))
    return covered_accesses, concurrent_accesses

def accesses_are_ordered(concurrent_accesses):
    highest_row = [0] * 4
    from cgra import N_ROWS
    for i in range (N_ROWS):
        for values in concurrent_accesses[i].values():
            for current_access in values:
                if highest_row[i] > current_access[0]:
                    return False
                else:
                    highest_row[i] = current_access[0]
    return True

def rearrange_accesses(first_list, second_list):
    order_pairs = []
    for second_pairs in second_list.values():
        for second_pair in second_pairs:
            order_pairs.append(second_pair[1])
    order_pairs_reversed = list(reversed(order_pairs))
    sorted_first_list = {}  
    for key, pairs in first_list.items():
        sorted_pairs = sorted(pairs, key=lambda x: order_pairs_reversed.index(x[1]) if x[1] in order_pairs_reversed else float('inf'))
        sorted_first_list[key] = sorted_pairs
    return sorted_first_list

def track_dependencies(self):
    from cgra import N_ROWS
    latency = [1] * 4 
    for i in range (N_ROWS):
        for values in self.concurrent_accesses[i].values():
            for current_access in values:
                # find the position of an access within the conflict, as well as that of the next dependency
                access_pos = find_position(self.concurrent_accesses[i], current_access[1]) + 1
                if i < N_ROWS - 1:
                    latency[current_access[1]] += access_pos - find_position(self.concurrent_accesses[i+1],current_access[1]) 
                else:
                    latency[current_access[1]] += access_pos
    return latency

def find_position(conflict_pos, column):
    for pairs in conflict_pos.items():
        for pair in pairs[1]:
            if pair[1] == column:
                return pairs[1].index(pair)
    return 0

def compute_latency_cc(self, dependencies):
    from cgra import N_ROWS, N_COLS, flag_poll_cnt
    ACTIVE_ROW_COEF =  bus_type_active_row_coef[self.bus_type]
    CPU_LOOP_INSTRS =  bus_type_cpu_loop_instrs[self.bus_type]
    mem_count = [0] * N_COLS
    latency_cc = max(dependencies)
    for r in range(N_ROWS):
        for c in range(N_COLS):                
            if self.cells[r][c].op in OPERATIONS_MEMORY_ACCESS:      
                mem_count[c] += 1
    if ACTIVE_ROW_COEF != 0:
        for i in range (N_ROWS):
            if mem_count[i] != 0:
                latency_cc += ACTIVE_ROW_COEF
    if CPU_LOOP_INSTRS != 0:
        flag_poll_cnt += latency_cc
        if flag_poll_cnt % (CPU_LOOP_INSTRS - 1) == 0:
            latency_cc += 1      
    return latency_cc

def display_characterization(cgra, pr):
    if any(item in pr for item in ["OP_MAX_LAT", "ALL_LAT_INFO"]):
        print("Longest instructions per cycle:\n")
        print("{:<8} {:<25} {:<10}".format("Cycle", "Instruction", "Latency (CC)"))
        for index, item in enumerate(cgra.instr_latency_cc):
            print("{:<2} {:<6} {:<25} {:<10}".format(index + 1, f'({item.instr2exec})', item.instr, item.latency_cc))
    if any(item in pr for item in ["TOTAL_LAT", "ALL_LAT_INFO"]):
        print(f'\nConfiguration time: {len(cgra.instrs)} CC')
        print(f'Time between end of configuration and start of first iteration: {math.ceil(14 + (len(cgra.instrs) * 3))} CC')
        print(f'Total time for all instructions: {cgra.total_latency_cc}')