import csv
import re

def counter(infile, outfile):
    with open(infile) as f:
        reader = csv.reader(f)
        counts = {'NOP': {}, 'INSTR': {}, 'PERC_INSTR': {}}
        current_timestamp = None

        for row in reader:
            # Se la riga contiene un timestamp
            match = re.match(r"(\d+)", row[0])
            if match:
                current_timestamp = match.group(1)
                # Inizializza i conteggi per questo timestamp
                if current_timestamp not in counts['NOP']:
                    counts['NOP'][current_timestamp] = 0
                    counts['INSTR'][current_timestamp] = 0
            else:
                # Aggiorna i conteggi
                counts['NOP'][current_timestamp] += row.count("NOP")
                counts['INSTR'][current_timestamp] += len(row) - row.count("NOP")

        # Calcolo delle percentuali
        for timestamp in counts['NOP']:
            total = counts['NOP'][timestamp] + counts['INSTR'][timestamp]
            if total > 0:
                counts['PERC_INSTR'][timestamp] = (counts['INSTR'][timestamp] / total)
            else:
                counts['PERC_INSTR'][timestamp] = 0

    # Formattazione dell'output
    out_string = "T\t" + "\t".join(counts['NOP'].keys()) + "\n"
    out_string += "NOP\t" + "\t".join(str(counts['NOP'][key]) for key in counts['NOP']) + "\n"
    out_string += "INSTR\t" + "\t".join(str(counts['INSTR'][key]) for key in counts['INSTR']) + "\n"
    out_string += "PERC_INSTR\t" + "\t".join(f"{counts['PERC_INSTR'][key]:.4f}" for key in counts['PERC_INSTR']) + "\n"

    with open(outfile, "w") as f:
        f.write(out_string)
