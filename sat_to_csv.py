import math
import csv

## Convert the output of SAT-MapIt into a csv file compatible with the simulator
def convert(infile, outfile, version=""):

    outfile = outfile.split(".")[0] + "{}." + outfile.split(".")[-1]
    outfile = outfile.format(version)

    # Read the input file (output of SAT-MapIt)
    with open(infile, "r") as f:
        lines = f.readlines()


    reading_conf = False
    time_stamp = 0
    configuration = []

    conf_set = []

    n_nodes = int(lines[0][-2])
    n_cols = int(math.sqrt(n_nodes))
    n_rows = n_cols
    print(n_nodes)
    print(n_cols)

    for line in lines:

        # Start reading instructions
        if line[0:3] == "T =":
            reading_conf = True
            configuration = []

            # stop reading, reached the last configuration
            if time_stamp > int(line[4]):
                reading_conf = False
                break
            else:
                # Here I only read the timestamp
                # print(line)
                time_stamp = int(line[4])
                conf_set.append(configuration)

        # Here I read the actual instructions
        if reading_conf:
            configuration.append(line)


    # Write the output file
    with open(outfile, "w") as f:
        writer = csv.writer(f)

        for conf in conf_set:
            time = conf[0]
            instrs = conf[1:]

            writer.writerow(time[-2])

            rows = [[instrs[(n_cols * r) + c][:-1] for c in range(n_cols)] for r in range(n_rows)]

            for r in rows:
                writer.writerow(r)

