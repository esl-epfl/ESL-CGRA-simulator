import copy
import os.path
import csv

OPERATIONS_MEMORY_ACCESS = ["LWD", "LWI", "SWD","SWI"]

def load_operation_characterization(operation_mapping, characterization_type):
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

def get_latency_cc(self):  
    from cgra import N_ROWS, N_COLS
    self.max_latency_instr = None
    mem_latency_cc = 0
    for r in range(N_ROWS):
        for c in range(N_COLS):             
            if self.max_latency_instr is None or self.cells[r][c].latency_cc > self.max_latency_instr.latency_cc:
                self.max_latency_instr = self.cells[r][c]
            if self.cells[r][c].op in OPERATIONS_MEMORY_ACCESS:      
                mem_latency_cc += 1
    # A memory access to a memory bank has a 2-cycle overhead, 
    # plus 1 additional cycle per PE trying to access it.
    if mem_latency_cc >= 1:
        mem_latency_cc += 1
    self.max_latency_instr.latency_cc = max(self.max_latency_instr.latency_cc, mem_latency_cc)
    if (self.exit):
        if (self.max_latency_instr.latency_cc > 2):
            self.max_latency_instr.latency_cc += 1
        
    self.max_latency_instr.instr2exec = self.instr2exec    
    self.instr_latency_cc.append(copy.copy(self.max_latency_instr))
    self.total_latency_cc += self.instr_latency_cc[-1].latency_cc

def display_characterization(cgra):
    print("Longest instructions per cycle:\n")
    print("{:<8} {:<25} {:<10}".format("Cycle", "Instruction", "Latency (CC)"))
    for index, item in enumerate(cgra.instr_latency_cc):
        print("{:<2} {:<6} {:<25} {:<10}".format(index + 1, f'({item.instr2exec})', item.instr, item.latency_cc))
    print("\nTotal latency for all instructions:", cgra.total_latency_cc, "CC")