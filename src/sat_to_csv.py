import math
import csv
import re
## Convert the output of SAT-MapIt into a csv file compatible with the simulator
def convert(infile, outfile, version=""):

    outfile = outfile.split(".")[0] + "{}." + outfile.split(".")[-1]
    outfile = outfile.format(version)

    # Read the input file (output of SAT-MapIt)
    with open(infile, "r") as f:
        lines = f.readlines()


    reading_conf = False
    last_time_stamp = 0
    current_time_stamp = 0
    configuration = []

    conf_set = []

    for line in lines:
        # Start reading instructions
        if line[0:3] == "T =":
            reading_conf = True
            configuration = []
            current_time_stamp = int(line.split(" ")[-1])

            # stop reading, reached the last configuration
            if last_time_stamp > current_time_stamp:
                reading_conf = False
                break
            else:
                # Here I only read the timestamp
                last_time_stamp = current_time_stamp
                conf_set.append(configuration)

        # Here I read the actual instructions
        if reading_conf:
            configuration.append(line)

    # counts the nodes and infer rows and columns (always assumes a squared mesh)
    n_nodes = len(conf_set[0][1:])
    n_cols = int(math.sqrt(n_nodes))
    n_rows = n_cols

    # Write the output file
    with open(outfile, "w") as f:
        writer = csv.writer(f)

        for conf in conf_set:

            time = conf[0]                          # Line with the timestamp
            time = int(time.split(" ")[-1][:-1])    # extract just the timestamp without the "\n" and parse to int

            instrs = conf[1:]   # Set of all instructions in the current configuration

            # Write the timestamp
            writer.writerow([time])

            rows = [[instrs[(n_cols * r) + c][:-1] for c in range(n_cols)] for r in range(n_rows)]

            for r in rows:
                writer.writerow(r)

def convert_sat_to_csv(sat_filepath, csv_filepath):
    with open(sat_filepath, 'r') as f:
        sat_lines = f.readlines()

    csv_rows = []
    current_instructions = []
    timestamp = None

    for line in sat_lines:
        line = line.strip()
        if re.match(r"T = \d+", line):
            if timestamp is not None:
                while current_instructions:
                    csv_rows.append(current_instructions[:4])
                    current_instructions = current_instructions[4:]
            timestamp = line[4:]
            csv_rows.append([timestamp, '', '', ''])
            current_instructions = []
        else:
            current_instructions.append(line)

    if current_instructions:
        while current_instructions:
            csv_rows.append(current_instructions[:4])
            current_instructions = current_instructions[4:]

    if csv_rows and csv_rows[-1] == ['0', '', '', '']:
        csv_rows.pop()
        
    # Write the result to a CSV file
    with open(csv_filepath, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        for row in csv_rows:
            writer.writerow(row + [''] * (4 - len(row)))