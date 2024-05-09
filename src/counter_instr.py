import csv
import re

def counter(infile, outfile):
    with open(infile) as f:
        reader = csv.reader(f)
        counts = {
            'NOP': {}, 
            'LW': {},  # Consider both LWD and LWI
            'SW': {},  # Consider both SWD and SWI
            'ADD': {},  # Consider both ADD and SSUB
            'MUL': {},  
            'OTHERS': {}  # For all other instructions
        }
        current_timestamp = None

        for row in reader:
            match = re.match(r"(\d+)", row[0])
            if match:
                current_timestamp = match.group(1)
                if current_timestamp not in counts:
                    for key in counts:
                        counts[key][current_timestamp] = 0  
            else:
                counts['NOP'][current_timestamp] += row.count("NOP")
                for instr in row:
                    if instr == "NOP":
                        continue
                    elif re.match(r"LW[D|I]\s+\w+", instr) or re.match(r"LW[D|I]\s+\w+,\s*\w+", instr):
                        counts['LW'][current_timestamp] += 1
                    elif re.match(r"SW[D|I]\s+\w+", instr) or re.match(r"SW[D|I]\s+\w+,\s*\w+", instr):
                        counts['SW'][current_timestamp] += 1
                    elif "ADD" in instr or "SSUB" in instr:  
                        counts['ADD'][current_timestamp] += 1
                    elif "MUL" in instr:
                        counts['MUL'][current_timestamp] += 1
                    else:
                        counts['OTHERS'][current_timestamp] += 1  

    
    out_string = "T\t" + "\t".join(counts['NOP'].keys()) + "\n"
    for key in counts:
        out_string += key + "\t" + "\t".join(str(counts[key][timestamp]) for timestamp in counts[key]) + "\n"

    with open(outfile, "w") as f:
        f.write(out_string)

