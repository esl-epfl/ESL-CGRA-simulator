import math, csv, os
import numpy as np

# ===================== EDIT THESE =====================
def func(x):
    return math.sin(x)

SCALE = 10000  # all values are round(real * SCALE) -> higher SCALE = more decimal points
X_MIN = 0.0
X_MAX = 2 * math.pi
SHIFT = 10  # segment width = 2^SHIFT in scaled units
ORDER = 10  # 1=linear, 2=quadratic, ...
X_TEST = 0.5  # test input
KERNEL = "sine_approx"  # output folder
# ======================================================

LUT_BASE = 100  # byte address where LUT starts in memory

# ---- Derived ----
x_min_int = round(X_MIN * SCALE)
x_max_int = round(X_MAX * SCALE)
seg_width = 1 << SHIFT  # e.g. 1024 for SHIFT=10
mask = seg_width - 1  # e.g. 1023
n_segs = (x_max_int - x_min_int) >> SHIFT
n_coeffs = ORDER + 1  # 2 for linear, 3 for quadratic
stride = n_coeffs * 4  # bytes per segment in LUT

# ================================================================
# BUILD THE LOOKUP TABLE
# ================================================================
# We divide the x range into n_segs segments, each of width seg_width.
# Inside each segment, we normalize the position to t in [0, 1):
#     t = (x_int - segment_start) / seg_width  =  dx / seg_width
#
# We fit a polynomial in t:
#     y(t) = c0 + c1*t + c2*t^2 + ...
#
# The real-valued coefficients are then scaled: c_int = round(c_real * SCALE)
#
# At runtime on the CGRA, the evaluation is:
#     t is computed as dx (an integer in [0, seg_width))
#     Horner: acc = c[K]; for k=K-1..0: acc = (acc * dx) >> SHIFT + c[k]
#     The >> SHIFT divides by seg_width, which is the "/ seg_width" in t.

segments = []
for i in range(n_segs):
    x_start = X_MIN + i * seg_width / SCALE
    # Sample ORDER+1 points at t = 0, 1/ORDER, 2/ORDER, ..., 1
    t_pts = [j / max(ORDER, 1) for j in range(ORDER + 1)]
    x_pts = [x_start + t * seg_width / SCALE for t in t_pts]
    y_pts = [func(x) for x in x_pts]
    # Fit polynomial y(t) = c0 + c1*t + c2*t^2 + ...
    coeffs = np.polyfit(t_pts, y_pts, ORDER)[::-1]  # index 0 = c0
    segments.append([round(c * SCALE) for c in coeffs])

# ================================================================
# WRITE MEMORY
# ================================================================
# Memory layout (all addresses are bytes, word size = 4 bytes):
#
#   Address 0     : x_test (input, scaled integer)
#   Address 4     : x_min  (scaled integer)
#   Address 100   : c0 of segment 0
#   Address 104   : c1 of segment 0
#   (if ORDER=2)  : c2 of segment 0 at 108
#   Address 100+stride : c0 of segment 1
#   ...etc...
#
# For ORDER=1 (linear), stride = 2*4 = 8 bytes per segment.
# Segment i starts at address LUT_BASE + i * stride.

os.makedirs(KERNEL, exist_ok=True)
x_test_int = round(X_TEST * SCALE)

with open(f"{KERNEL}/memory.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Address", "Data"])
    w.writerow([0, x_test_int])
    w.writerow([4, x_min_int])
    for i, coeffs in enumerate(segments):
        for k, c in enumerate(coeffs):
            w.writerow([LUT_BASE + i * stride + k * 4, c])

# ================================================================
# WRITE INSTRUCTIONS
# ================================================================
# The CGRA is a 4x4 grid of PEs. Each "instruction" configures ALL 16 PEs
# for one clock step. PEs talk to neighbors via routing (RCR, RCL, RCT, RCB).
#
# PE layout used:
#   PE(row0, col0) : loads x, computes dx. Its output holds dx afterwards.
#   PE(row0, col1) : loads x_min. Used once then idle.
#   PE(row1, col0) : workhorse. Computes offset, Horner accumulator, stores.
#   PE(row2, col0) : holds LUT base address, loads coefficients in parallel.
#   PE(row0, col3) : EXIT signal.
#
# Routing connections used:
#   RCR at (0,0) reads PE(0,1).old_out  -> to get x_min
#   RCT at (1,0) reads PE(0,0).old_out  -> to get dx (or index before that)
#   RCT at (2,0) reads PE(1,0).old_out  -> to get offset
#   RCB at (1,0) reads PE(2,0).old_out  -> to get loaded coefficient
#
# No FXPMUL. All multiply is SMUL (int32*int32→int32), divide is SRA/SRT.


def grid(ops):
    g = [["NOP"] * 4 for _ in range(4)]
    for (r, c), op in ops.items():
        g[r][c] = op
    return g


instrs = []

# Instr 0: Load x into PE(0,0).R0, load x_min into PE(0,1).R0
#   Column 0 reads from load_addr[0]=0 → gets x_test
#   Column 1 reads from load_addr[1]=4 → gets x_min
instrs.append(grid({(0, 0): "LWD R0", (0, 1): "LWD R0"}))

# Instr 1: PE(0,0) computes dx_total = x - x_min
#   RCR at (0,0) = PE(0,1).old_out = x_min (loaded last step)
#   After this, PE(0,0).out = dx_total, PE(0,0).R0 = dx_total
instrs.append(grid({(0, 0): "SSUB R0, R0, RCR"}))

# Instr 2: PE(0,0) computes index = dx_total >> SHIFT (logical shift right)
#   index tells us which segment x falls in.
#   After this, PE(0,0).out = index, R1 = index
instrs.append(grid({(0, 0): f"SRT R1, R0, {SHIFT}"}))

# Instr 3: Two things happen in parallel:
#   PE(0,0): dx = dx_total AND mask  (extract lower SHIFT bits = position within segment)
#   PE(1,0): offset = index * stride  (byte offset into LUT for this segment)
#     RCT at (1,0) = PE(0,0).old_out = index (from instr 2)
instrs.append(
    grid(
        {
            (0, 0): f"LAND R0, R0, {mask}",
            (1, 0): f"SMUL R0, RCT, {stride}",
        }
    )
)

# Instr 4: Two things in parallel:
#   PE(1,0): addr_high = offset + LUT_BASE + ORDER*4  (address of highest coeff)
#   PE(2,0): base_addr = offset + LUT_BASE  (base address of this segment's c0)
#     RCT at (2,0) = PE(1,0).old_out = offset (from instr 3)
instrs.append(
    grid(
        {
            (1, 0): f"SADD R1, R0, {LUT_BASE + ORDER * 4}",
            (2, 0): f"SADD R0, RCT, {LUT_BASE}",
        }
    )
)

# Instr 5: PE(1,0) loads c[ORDER] from memory into R1 (the accumulator)
#   LWI = Load Word Indirect: R1 ← memory[R1]
instrs.append(grid({(1, 0): "LWI R1, R1"}))

# Horner loop: for each coefficient from ORDER-1 down to 0
#   acc = (acc * dx) >> SHIFT + c[k]
# This takes 3 instructions per iteration, with coeff loading overlapped.
for k in range(ORDER - 1, -1, -1):
    # Step A: PE(1,0) multiplies: acc * dx
    #   RCT at (1,0) = PE(0,0).old_out = dx (has been stable since instr 3)
    # In parallel, PE(2,0) computes address of c[k]
    instrs.append(
        grid(
            {
                (1, 0): "SMUL R1, R1, RCT",
                (2, 0): f"SADD ROUT, R0, {k * 4}",
            }
        )
    )
    # Step B: PE(1,0) shifts: acc >>= SHIFT  (this is the "divide by seg_width")
    # In parallel, PE(2,0) loads c[k] from memory
    instrs.append(
        grid(
            {
                (1, 0): f"SRA R1, R1, {SHIFT}",
                (2, 0): "LWI R1, ROUT",
            }
        )
    )
    # Step C: PE(1,0) adds: acc += c[k]
    #   RCB at (1,0) = PE(2,0).old_out = c[k] (just loaded)
    instrs.append(grid({(1, 0): "SADD R1, R1, RCB"}))

# Final instruction: store result and exit
instrs.append(grid({(1, 0): "SWD R1", (0, 3): "EXIT"}))

with open(f"{KERNEL}/instructions.csv", "w", newline="") as f:
    w = csv.writer(f)
    for t, g in enumerate(instrs):
        w.writerow([t])
        for row in g:
            w.writerow(row)

# ================================================================
# SELF-CHECK (pure Python, same math the CGRA does)
# ================================================================
dx_total = x_test_int - x_min_int
index = dx_total >> SHIFT
dx = dx_total & mask
seg = segments[index]
acc = seg[ORDER]
for k in range(ORDER - 1, -1, -1):
    acc = (acc * dx >> SHIFT) + seg[k]
expected = round(func(X_TEST) * SCALE)

print(
    f"ORDER={ORDER}, SHIFT={SHIFT}, segments={n_segs}, "
    f"instructions={len(instrs)}, LUT words={n_segs * n_coeffs}"
)
print(f"x={X_TEST} -> x_int={x_test_int}, index={index}, dx={dx}")
print(f"  segment[{index}] coeffs = {seg}")
print(f"  Horner result = {acc}  ({acc/SCALE:.6f})")
print(f"  Expected      = {expected}  ({func(X_TEST):.6f})")
print(f"  Error         = {abs(acc - expected)/SCALE:.2e}")
print(f"Files: {KERNEL}/instructions.csv, {KERNEL}/memory.csv")
