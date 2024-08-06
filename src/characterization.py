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

def get_latency_cc(self, prs):  
    bus_type = next((item for item in BUS_TYPES if item in prs), "ONE-TO-M")
    self.max_latency_instr = None
    mem_latency_cc = find_longest_operation(self)
    mem_latency_cc = adjust_latency_for_bus(self, mem_latency_cc, bus_type)
    if mem_latency_cc > self.max_latency_instr.latency_cc:
        self.max_latency_instr.latency_cc = mem_latency_cc
        self.max_latency_instr.instr = f'MEM ({self.max_latency_instr.instr})'  
    if (self.exit):
        self.max_latency_instr.latency_cc += 1      
    self.max_latency_instr.instr2exec = self.instr2exec    
    self.instr_latency_cc.append(copy.copy(self.max_latency_instr))
    self.total_latency_cc += self.instr_latency_cc[-1].latency_cc

def find_longest_operation(self):
    from cgra import N_ROWS, N_COLS
    self.mem_count = [0] * N_COLS
    mem_latency_cc = 0
    for r in range(N_ROWS):
        for c in range(N_COLS):    
            self.cells[r][c].latency_cc = int(operation_latency_mapping[self.cells[r][c].op])                
            if self.max_latency_instr is None or self.cells[r][c].latency_cc > self.max_latency_instr.latency_cc:
                self.max_latency_instr = self.cells[r][c]
            if self.cells[r][c].op in OPERATIONS_MEMORY_ACCESS:      
                mem_latency_cc += 1
                self.mem_count[c] += 1
    if mem_latency_cc >= 1:
        mem_latency_cc += 1
    return mem_latency_cc

def adjust_latency_for_bus(self, mem_latency_cc, bus_type):
    from cgra import N_ROWS, flag_poll_cnt
    ACTIVE_ROW_COEF =  bus_type_active_row_coef[bus_type]
    CPU_LOOP_INSTRS =  bus_type_cpu_loop_instrs[bus_type]
    for i in range (N_ROWS):
            if self.mem_count[i] != 0:
                mem_latency_cc += ACTIVE_ROW_COEF
    if CPU_LOOP_INSTRS != 0:
        flag_poll_cnt += mem_latency_cc
        if flag_poll_cnt % (CPU_LOOP_INSTRS - 1) == 0:
            mem_latency_cc += 1    
    if bus_type == "INTERLEAVED":
        concurrent_accesses = group_sequential_accesses(self)
        mem_latency_cc = find_longest_sequence(concurrent_accesses)
    return mem_latency_cc

def group_sequential_accesses(self):
    from cgra import N_ROWS, N_COLS
    self.curr_lwd = [0] * 4
    self.curr_swd = [0] * 4
    covered_accesses = []
    # count the number of direct accesses per column
    for r in range(N_ROWS):
        for c in range(N_COLS): 
             if self.cells[r][c].op in OPERATIONS_MEMORY_ACCESS:     
                if self.cells[r][c].op == "LWD":
                    self.curr_lwd[c] += 1
                if self.cells[r][c].op == "SWD":
                    self.curr_swd[c] += 1
    concurrent_accesses = [{} for _ in range(4)]
    # reorder memory accesses to group into concurrent executions
    # covered_accesses tracks the accesses that have already been visited
    for r in range(N_ROWS):
        for c in range(N_COLS):  
            if self.cells[r][c].op in OPERATIONS_MEMORY_ACCESS and (r, c) not in covered_accesses:
                index_pos = record_bank_access(self, r, c)
                covered_accesses.append((r, c))
                if index_pos not in concurrent_accesses[r]:
                    concurrent_accesses[r][index_pos] = []
                concurrent_accesses[r][index_pos].append((r, c) )
            else:
                for k in range(N_ROWS):
                    if self.cells[k][c].op in OPERATIONS_MEMORY_ACCESS and (k, c) not in covered_accesses:
                        index_pos = record_bank_access(self, k, c)
                        covered_accesses.append((k, c))
                        if index_pos not in concurrent_accesses[r]:
                            concurrent_accesses[r][index_pos] = []
                        concurrent_accesses[r][index_pos].append((k, c))
                        break
    if not accesses_are_ordered(concurrent_accesses):
        for i in range(N_ROWS - 1, 0, -1):
            concurrent_accesses[i-1] = rearrange_accesses(concurrent_accesses[i-1], concurrent_accesses[i]) 
    return concurrent_accesses

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

def find_longest_sequence(concurrent_accesses):
    from cgra import N_ROWS
    latency = [1] * 4 
    for i in range (N_ROWS):
        for values in concurrent_accesses[i].values():
            for current_access in values:
                # find the position of an access within the conflict, as well as that of the next dependency
                access_pos = find_position(concurrent_accesses[i], current_access[1]) + 1
                if i < N_ROWS - 1:
                    latency[current_access[1]] += access_pos - find_position(concurrent_accesses[i+1],current_access[1]) 
                else:
                    latency[current_access[1]] += access_pos
    return max(latency)

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

def find_position(conflict_pos, column):
    for pairs in conflict_pos.items():
        for pair in pairs[1]:
            if pair[1] == column:
                return pairs[1].index(pair)
    return 0

def record_bank_access(self, r, c) :
    if self.cells[r][c].op == "LWD":
        addr = self.load_addr[self.cells[r][c].col] - (4 * self.curr_lwd[c])
        self.curr_lwd[c] -= 1
    elif self.cells[r][c].op == "LWI":
        instr = self.cells[r][c].instr
        instr = instr.split()
        addr = self.cells[r][c].fetch_val(instr[2])
    elif self.cells[r][c].op == "SWD":
        addr = self.store_addr[self.cells[r][c].col] - (4 * self.curr_swd[c])
        index_pos = int(((addr - self.init_store[0]) / 4) % 8)
        self.curr_swd[c] -= 1
        return index_pos
    elif self.cells[r][c].op == "SWI":
        instr = self.cells[r][c].instr
        instr = instr.split()
        addr = self.cells[r][c].fetch_val(instr[2]) 
    index_pos = int(((addr - sorted(self.memory)[0][0]) / 4) % 8)
    return index_pos

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
    