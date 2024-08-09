EXT             = ".csv"
FILENAME_INSTR  = "instructions"
FILENAME_MEM    = "memory"
FILENAME_INP    = "inputs"
FILENAME_OUP    = "outputs"
FILENAME_MEM_O  = "memory_out"
WORD_SIZE   = 4

class MEMORY:
    def __init__( self,bus_type="INTERLEAVED", spacing=4, n_banks=8, bank_size=32000):
        self.bus_type = bus_type
        self.spacing = spacing
        self.n_banks = n_banks
        self.bank_size = bank_size
        self.flag_poll_cnt = 0

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

