
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