"""
Convert old flat memory.csv → new banked in.csv for RTL sim.

Old format:  Address,Data        (single flat address space)
New format:  col_id,addr,data,type  (per-column scratchpad banks)

The mapping depends on which PEs read which addresses:
  - LWD entries: each column reads sequentially from its own bank starting at 0x0000
  - LWI entries (LUT): stay at original addresses in whichever column does indirect loads

Edit the params below for your variant, then run:
    python mem_to_banked.py
"""

import csv, os, struct

# ========================== PARAMS =============================
# INPUT_FILE  = "pareto_out/QUAD_T3_S12/memory.csv"
INPUT_FILE  = "../sinusoidal/sine_approx/memory_out.csv"
OUTPUT_FILE = "out.csv"

# Which flat addresses are LWD inputs, and which column reads them.
# Format: {flat_addr: (col_id, local_addr_in_bank)}
# For PIPE3: col 0 reads x_test from flat 0, col 1 reads x_min from flat 4
LWD_MAP = {
    0: (0, 0x0000),   # x_test  → col 0, addr 0x0000
    4: (1, 0x0000),   # x_min   → col 1, addr 0x0000
}

# Everything else (LUT coefficients accessed via LWI) goes to this column,
# keeping its original byte address.
LUT_COL = 0

# Output data type for the CSV ('hex' or 'int')
DATA_TYPE = "hex"
# ===============================================================


def signed_to_u32(val):
    """int32 → unsigned 32-bit (2's complement for negatives)."""
    return struct.unpack('<I', struct.pack('<i', val))[0]


def main():
    # read old flat memory
    entries = []
    with open(INPUT_FILE) as f:
        reader = csv.reader(f)
        header = next(reader)  # skip "Address,Data"
        for row in reader:
            if len(row) >= 2:
                addr = int(row[0])
                data = int(row[1])
                entries.append((addr, data))

    # split into LWD inputs vs LUT/other entries
    banked = []  # list of (col_id, local_addr, data)
    for addr, data in entries:
        if addr in LWD_MAP:
            col, local_addr = LWD_MAP[addr]
            banked.append((col, local_addr, data))
        else:
            # LWI-accessed data: keep original address, put in LUT_COL
            banked.append((LUT_COL, addr, data))

    # sort by (col, addr) for readability
    banked.sort(key=lambda x: (x[0], x[1]))

    # write new format
    with open(OUTPUT_FILE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["col_id", "addr", "data", "type"])
        for col, addr, data in banked:
            u32 = signed_to_u32(data)
            w.writerow([col, f"0x{addr:04X}", f"0x{u32:X}", DATA_TYPE])

    # summary
    cols_used = sorted(set(c for c, _, _ in banked))
    print(f"Converted {len(entries)} entries → {OUTPUT_FILE}")
    for c in cols_used:
        n = sum(1 for col, _, _ in banked if col == c)
        print(f"  col {c}: {n} entries")


if __name__ == "__main__":
    main()