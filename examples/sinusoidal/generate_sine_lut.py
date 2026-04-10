"""
Piecewise polynomial function approximation for the ESL-CGRA.

Computes y = f(x) using a lookup table of pre-fitted polynomials.
Everything is integer arithmetic — values are scaled by SCALE (no float on hw).

How it works:
  - The x range is split into N segments of width 2^SHIFT (power of 2 so we
    can divide with a bit shift instead of actual division).
  - For each segment, we precompute polynomial coefficients before (on your PC)
    by fitting ORDER+1 sample points of the real function.
  - At runtime the CGRA finds which segment x lands in, computes how far into
    the segment it is (dx), and evaluates y = c0 + c1*(dx/w) + c2*(dx/w)^2 + ...
    via Horner's method: acc = c[K]; for k=K-1..0: acc = (acc*dx)>>SHIFT + c[k]
  - The >>SHIFT is the division by segment width. SMUL+SRA, all int32.

Scaling to higher orders:
  - ORDER=1 (linear, y=ax+b): 2 coeffs/segment, 10 instructions, 3cc Horner
  - ORDER=2 (quadratic): 3 coeffs/segment, 13 instructions, 6cc Horner
  - ORDER=N: N+1 coeffs/seg, 7+3N instructions
  Accuracy improves with higher order and smaller SHIFT (= more segments).
  Just change ORDER below and rerun. Memory and instructions are regenerated.

Edit the params, run the script, feed the outputs to the simulator.
"""########################################################################

import math, csv, os
import numpy as np


# ========================== PARAMS =============================
def func(x):
    return math.sin(x)


SCALE = 10000  # real_value * SCALE = integer stored in memory
X_MIN = 0.0
X_MAX = 2 * math.pi
SHIFT = 10  # segment width = 2^SHIFT scaled units (1024 here)
ORDER = 1  # polynomial order: 1=linear, 2=quad, 3=cubic...
X_TEST = 1.0  # test input baked into memory.csv
KERNEL = "sine_approx"  # output folder (to match with ipynb)
# ===============================================================

LUT_BASE = 100  # byte address where coefficient table starts

# -- derived stuff --
x_min_int = round(X_MIN * SCALE)
x_max_int = round(X_MAX * SCALE)
seg_w = 1 << SHIFT  # segment width in scaled units
mask = seg_w - 1  # for extracting dx via AND
n_segs = (x_max_int - x_min_int) >> SHIFT
n_coeffs = ORDER + 1
stride = n_coeffs * 4  # bytes per segment in the LUT

# ==============================================================
# LUT: fit a degree-ORDER polynomial per segment
# ==============================================================
# Within each segment we define t = dx / seg_w, so t in [0, 1).
# We sample f(x) at ORDER+1 points, polyfit in t, store coefficients
# as integers (round(c_real * SCALE)).
#
# For ORDER=1 this just stores [sin(x_start), sin(x_end)-sin(x_start)].

segments = []
for i in range(n_segs):
    x0 = X_MIN + i * seg_w / SCALE
    t_pts = [j / max(ORDER, 1) for j in range(ORDER + 1)]  # t = 0, 1/O, ..., 1
    x_pts = [x0 + t * seg_w / SCALE for t in t_pts]
    y_pts = [func(x) for x in x_pts]
    # polyfit returns highest-order first, we want c0 first
    coeffs = np.polyfit(t_pts, y_pts, ORDER)[::-1]
    segments.append([round(c * SCALE) for c in coeffs])


# ==============================================================
# MEMORY: input values at addr 0,4 then LUT at addr 100+
# ==============================================================
# addr 0:   x (scaled)
# addr 4:   x_min (scaled)
# addr 100: c0 of seg 0
# addr 104: c1 of seg 0
# ...########################################################################
# addr 100 + i*stride + k*4: c_k of seg i

os.makedirs(KERNEL, exist_ok=True)
x_test_int = round(X_TEST * SCALE)

with open(f"{KERNEL}/memory.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Address", "Data"])
    w.writerow([0, x_test_int])
    w.writerow([4, x_min_int])
    for i, cs in enumerate(segments):
        for k, c in enumerate(cs):
            w.writerow([LUT_BASE + i * stride + k * 4, c])

# ==============================================================
# INSTRUCTIONS: pipelined across 3 PEs
# ==============================================================
# PE(0,0) — loads x, computes dx, then just sits there holding dx in its output
# PE(1,0) — the workhorse: offset calc, Horner accumulator, final store
# PE(2,0) — loads coefficients from LUT in parallel with PE(1,0)'s arithmetic
# PE(0,1) — loads x_min once (instr 0), idle after
# PE(0,3) — EXIT
#
# Routing (PEs read their neighbor's PREVIOUS output):
#   PE(0,0) reads PE(0,1) via RCR  — to get x_min
#   PE(1,0) reads PE(0,0) via RCT  — to get index, then dx
#   PE(2,0) reads PE(1,0) via RCT  — to get byte offset
#   PE(1,0) reads PE(2,0) via RCB  — to get loaded coefficients
#
# The pipeline overlap: while PE(1,0) does SMUL or SRA, PE(2,0)
# computes the next coefficient address or loads it from memory.
# So the 3-step Horner iteration only adds 3 cycles, not 5.


def grid(ops):
    """One 4x4 instruction. Only fill in the PEs that do something."""
    g = [["NOP"] * 4 for _ in range(4)]
    for (r, c), op in ops.items():
        g[r][c] = op
    return g


instrs = []

# -- phase 1: find segment index and dx --

# 0: load x and x_min in parallel (col0 reads addr 0, col1 reads addr 4)
instrs.append(grid({(0, 0): "LWD R0", (0, 1): "LWD R0"}))

# 1: dx_total = x - x_min
instrs.append(grid({(0, 0): "SSUB R0, R0, RCR"}))

# 2: index = dx_total / seg_w  (done as >>SHIFT because seg_w is a power of 2)
instrs.append(grid({(0, 0): f"SRT R1, R0, {SHIFT}"}))

# 3: dx = dx_total % seg_w  (done as AND mask — extracts the lower SHIFT bits)
#    offset = index * stride  (on PE(1,0), in parallel)
instrs.append(
    grid(
        {
            (0, 0): f"LAND R0, R0, {mask}",  # dx — stays in PE(0,0).out from here on
            (1, 0): f"SMUL R0, RCT, {stride}",  # RCT = index from instr 2
        }
    )
)

# -- phase 2: set up addresses, load top coefficient --

# 4: compute addr of c[ORDER] and base addr of segment
instrs.append(
    grid(
        {
            (1, 0): f"SADD R1, R0, {LUT_BASE + ORDER * 4}",  # addr of highest coeff
            (2, 0): f"SADD R0, RCT, {LUT_BASE}",  # base addr (for loading lower coeffs)
        }
    )
)

# 5: load c[ORDER] into the accumulator
instrs.append(grid({(1, 0): "LWI R1, R1"}))

# -- phase 3: Horner loop, 3 instrs per order --
# acc = c[K]; for k = K-1 .. 0: acc = (acc * dx) >> SHIFT + c[k]

for k in range(ORDER - 1, -1, -1):
    # A: acc *= dx  |  PE(2,0) computes addr of c[k]
    instrs.append(
        grid(
            {
                (1, 0): "SMUL R1, R1, RCT",  # RCT = dx (stable since instr 3)
                (2, 0): f"SADD ROUT, R0, {k * 4}",  # addr = base + k*4
            }
        )
    )
    # B: acc >>= SHIFT  |  PE(2,0) loads c[k] from memory
    instrs.append(
        grid(
            {
                (1, 0): f"SRA R1, R1, {SHIFT}",  # integer division by seg_w
                (2, 0): "LWI R1, ROUT",  # loads c[k], will be in old_out next cycle
            }
        )
    )
    # C: acc += c[k]
    instrs.append(grid({(1, 0): "SADD R1, R1, RCB"}))  # RCB = PE(2,0).old_out = c[k]

# -- done: store and exit --
instrs.append(grid({(1, 0): "SWD R1", (0, 3): "EXIT"}))

# write it out
with open(f"{KERNEL}/instructions.csv", "w", newline="") as f:
    w = csv.writer(f)
    for t, g in enumerate(instrs):
        w.writerow([t])
        for row in g:
            w.writerow(row)


# ==============================================================
# SELF-CHECK: replicate the CGRA math in python to verify
# ==============================================================
# This does exactly what the hardware does: same shifts, same order.
# Note: max intermediate value = SCALE * seg_w = 10000 * 1024 = approx. 10M,
# well under int32 max (2.1B), so no overflow.

dx_total = x_test_int - x_min_int
index = dx_total >> SHIFT  # which segment
dx = dx_total & mask  # position within segment
seg = segments[index]
acc = seg[ORDER]  # start with highest coeff
for k in range(ORDER - 1, -1, -1):
    acc = (acc * dx >> SHIFT) + seg[k]
expected = round(func(X_TEST) * SCALE)

print(
    f"ORDER={ORDER}  SHIFT={SHIFT}  segs={n_segs}  "
    f"instrs={len(instrs)}  LUT_words={n_segs * n_coeffs}"
)
print(f"x={X_TEST} -> x_int={x_test_int}  index={index}  dx={dx}")
print(f"  seg[{index}] = {seg}")
print(f"  result   = {acc}  ({acc/SCALE:.6f})")
print(f"  expected = {expected}  ({func(X_TEST):.6f})")
print(f"  error    = {abs(acc - expected)/SCALE:.2e}")
print(f"-> {KERNEL}/instructions.csv  {KERNEL}/memory.csv")
