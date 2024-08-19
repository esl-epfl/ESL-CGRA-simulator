EXT             = ".csv"
FILENAME_INSTR  = "instructions"
FILENAME_MEM    = "memory"
FILENAME_INP    = "inputs"
FILENAME_OUP    = "outputs"
FILENAME_MEM_O  = "memory_out"
WORD_SIZE   = 4

class MEMORY:
    def __init__( self,bus_type="ONE-TO-M", word_size_B=4, banks_n=8, bank_size_B=32000):
        self.bus_type = bus_type
        self.word_size_B = word_size_B
        self.banks_n = banks_n
        self.bank_size_B = bank_size_B
        self.flag_poll_cnt = 0

def clear_memory( name, version=""):
        import csv
        filedir     = "./"+name+"/"
        with open(filedir + FILENAME_MEM + version + EXT,"w+",  newline='') as f:
            csv.writer(f).writerow(["Address", "Data"])

def add_memory_region( name, start, vals, version=""):
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

