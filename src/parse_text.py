import csv
import re
def read_strings(file_path):
    with open(file_path, newline='', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        strings = [row[0] for row in reader]
    return strings

def find_lines_with_strings(strings, text_file_path):
    matching_lines_dict = {s: [] for s in strings}
    with open(text_file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()
        for line in lines:
            if "warning" not in line.lower():
                for s in strings:
                    if s in line:
                        matching_lines_dict[s].append(line.strip())
                        break  # Stop searching after the first match for the current line
    return matching_lines_dict

def add_rc(strings, row, col):
    strings.append(f"rc_row_gen_{row}__rc_col_gen_{col}__rc_i")
    strings.append(f"datapath_{(15-((row*4)+col))}")
    strings.append(f"reg_file_REGFILE_DEPTH4_REGFILE_WIDTH32_{(15-((row*4)+col))}")
    strings.append(f"mux_MUX_NUM_INPUTS16_MUX_INPUTS_WIDTH32_{(2*(15-((row*4)+col)))}")
    strings.append(f"alu_{(15-((row*4)+col))}") 
    strings.append(f"mux_MUX_NUM_INPUTS16_MUX_INPUTS_WIDTH32_{(2*(15-((row*4)+col)))+1}")
    strings.append(f"mux_MUX_NUM_INPUTS8_MUX_INPUTS_WIDTH2_{(15-((row*4)+col))}")
    strings.append(f"rc_conf_registers (conf_reg_file_{(15-((row*4)+col))})")
    return strings


def computePwr():
    # strings_file = '/home/aspros/Documents/GitHub/ESL-CGRA-simulator/power_reports/add_pwr.csv'   # File containing the strings
    # text_file = '/home/aspros/Documents/GitHub/ESL-CGRA-simulator/power_reports/add_pwr.csv'       # File to search through
    output_file = 'output.txt'  # File to write the matching lines
    strings_file = 'power_reports/add_pwr.csv'
    text_file = 'power_reports/kernels/add_n_others_hier.rpt'
    # text_file = 'power_reports/kernels/reversebits_b_hier.rpt'
    # power_reports/kernels/reversebits_b_hier.rpt
    row = 1
    col = 2
    
    strings = read_strings(strings_file)
    matching_lines_dict = find_lines_with_strings(strings, text_file)
    
    with open(output_file, 'w') as f:
        for s in strings:
            if s in matching_lines_dict:
                for line in matching_lines_dict[s]:
                    f.write(line + '\n')



# cgra_context_memory_decoder_i
# cgra_data_handler_i
# cgra_rcs_i
# cgra_ctrl_i
# cgra_synchronizer_i
# rcs_col_cg_gen_
# cgra_top_i
# clk_gate_rcs_res_reg_reg_
# rc_row_gen