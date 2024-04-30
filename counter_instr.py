import csv
import re

def counter(infile, outfile):
    with open(infile) as f:
        reader = csv.reader(f)
        counts = {
            'NOP': {}, 
            'LW': {},  # Unifica LWD e LWI in LW
            'SW': {},  # Unifica SWD e SWI in SW
            'ADD': {},  # Ora include anche SSUB
            'MUL': {},  # Categoria MUL
            'OTHERS': {}  # Categoria per le istruzioni non specificate
        }
        current_timestamp = None

        for row in reader:
            match = re.match(r"(\d+)", row[0])
            if match:
                current_timestamp = match.group(1)
                if current_timestamp not in counts:
                    for key in counts:
                        counts[key][current_timestamp] = 0  # Inizializzazione dei conteggi
            else:
                counts['NOP'][current_timestamp] += row.count("NOP")
                for instr in row:
                    if instr == "NOP":
                        continue
                    elif re.match(r"LW[D|I]\s+\w+", instr) or re.match(r"LW[D|I]\s+\w+,\s*\w+", instr):
                        counts['LW'][current_timestamp] += 1
                    elif re.match(r"SW[D|I]\s+\w+", instr) or re.match(r"SW[D|I]\s+\w+,\s*\w+", instr):
                        counts['SW'][current_timestamp] += 1
                    elif "ADD" in instr or "SSUB" in instr:  # Ora include SSUB nella categoria ADD
                        counts['ADD'][current_timestamp] += 1
                    elif "MUL" in instr:
                        counts['MUL'][current_timestamp] += 1
                    else:
                        counts['OTHERS'][current_timestamp] += 1  # Tutte le altre istruzioni

    # Formattazione dell'output
    out_string = "T\t" + "\t".join(counts['NOP'].keys()) + "\n"
    for key in counts:
        out_string += key + "\t" + "\t".join(str(counts[key][timestamp]) for timestamp in counts[key]) + "\n"

    with open(outfile, "w") as f:
        f.write(out_string)

