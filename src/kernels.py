
EXT             = ".csv"
FILENAME_INSTR  = "instructions"
FILENAME_MEM    = "memory"
FILENAME_INP    = "inputs"
FILENAME_OUP    = "outputs"
FILENAME_MEM_O  = "memory_out"
WORD_SIZE   = 4

def kernel_new( name, dim=4 ):
    import os, csv
    filedir     = "./"+name+"/"

    if os.path.isdir(filedir):
        print("Kernel", name, "already exists!")
        return
    os.makedirs(os.path.dirname(filedir), exist_ok=True)

    with open(filedir + FILENAME_INP + EXT,"w+") as f:
        csv.writer(f).writerow([""]*dim)
    with open(filedir + FILENAME_MEM + EXT,"w+") as f:
        csv.writer(f).writerow(["Address", "Data"])
        csv.writer(f).writerow(["0", "0"])

    print("Kernel", name, "created successfuly!")


def kernel_clear_memory( name, version=""):
    import csv
    filedir     = "./"+name+"/"
    with open(filedir + FILENAME_MEM + version + EXT,"w+",  newline='') as f:
        csv.writer(f).writerow(["Address", "Data"])


def kernel_add_memory_region( name, start, vals, version=""):
    import csv
    mem     = []
    region  = []
    filedir     = "./"+name+"/"
    for i in range(len(vals)):
        region.append([ start + i*WORD_SIZE,vals[i]])

    try:
        with open(filedir + FILENAME_MEM + version + EXT) as f:
            for row in csv.reader(f): mem.append(row)

        for row in region: mem.append(row)

        with open(filedir + FILENAME_MEM + version + EXT,"w", newline='') as f:
            for row in mem: csv.writer(f).writerow(row)
    except:
        print("Could not open memory file")



