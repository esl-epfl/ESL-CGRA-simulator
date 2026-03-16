"""
Generate CGRA instructions and memory for piecewise polynomial sine (or any function).
Edit the parameters below, then run: python generate_sine_lut.py
"""

import math, csv, os, json
import numpy as np


# ===================== EDIT THESE =====================
def func(x):
    return math.sin(x)


SCALE = 10000  # values are integers = round(real_value * SCALE)
X_MIN = 0.0
X_MAX = 2 * math.pi
SHIFT = 10  # segment width = 2^SHIFT in scaled-x units
ORDER = 1  # 1 = linear (y=ax+b), 2 = quadratic, 3 = cubic ...
X_TEST = 1.0  # test input placed in memory
KERNEL = "sine_approx"  # output folder
# ======================================================

# Fixed addresses
LUT_BASE = 100
OUTPUT_ADDR = 10000

# Derived constants
x_min_int = round(X_MIN * SCALE)
x_max_int = round(X_MAX * SCALE)
seg_width = 1 << SHIFT
mask = seg_width - 1
n_segs = (x_max_int - x_min_int) >> SHIFT
n_coeffs = ORDER + 1
stride = n_coeffs * 4  # bytes per segment in LUT


# ---- Build LUT ----
# For each segment, fit a polynomial y(t) = c0 + c1*t + c2*t^2 + ...
# where t = dx / 2^SHIFT  (t in [0,1) within the segment)
# Coefficients are stored as round(c_real * SCALE).

segments = []
for i in range(n_segs):
    x_start = X_MIN + i * seg_width / SCALE
    t_pts = [j / max(ORDER, 1) for j in range(ORDER + 1)]
    x_pts = [x_start + t * seg_width / SCALE for t in t_pts]
    y_pts = [func(x) for x in x_pts]
    coeffs = np.polyfit(t_pts, y_pts, ORDER)[::-1]  # c0, c1, c2, ...
    segments.append([round(c * SCALE) for c in coeffs])


# ---- Write memory.csv ----
os.makedirs(KERNEL, exist_ok=True)
x_test_int = round(X_TEST * SCALE)

with open(f"{KERNEL}/memory.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Address", "Data"])
    w.writerow([0, x_test_int])  # x input
    w.writerow([4, x_min_int])  # x_min
    for i, coeffs in enumerate(segments):
        for k, c in enumerate(coeffs):
            w.writerow([LUT_BASE + i * stride + k * 4, c])


# ---- Write instructions.csv ----
# Pipelined across the 4x4 grid. PE layout:
#
#   PE(0,0) : loads x, computes dx. Holds dx in its output forever.
#   PE(0,1) : loads x_min.
#   PE(1,0) : computes offset, runs Horner accumulator, stores result.
#   PE(2,0) : holds LUT base address, loads coefficients for Horner.
#   PE(0,3) : EXIT.
#
# Routing used:
#   RCR(0,0) = PE(0,1).old_out  -> get x_min
#   RCT(1,0) = PE(0,0).old_out  -> get index, then dx
#   RCT(2,0) = PE(1,0).old_out  -> get offset
#   RCB(1,0) = PE(2,0).old_out  -> get loaded coefficients
#
# No FXPMUL. Multiply is SMUL (int32), shift is SRA (arithmetic).
#
# Total instructions = 7 + 3 * ORDER


def grid(ops):
    """Build one 4x4 instruction. ops = {(row,col): "OP", ...}"""
    g = [["NOP"] * 4 for _ in range(4)]
    for (r, c), op in ops.items():
        g[r][c] = op
    return g


instrs = []

# -- Setup (6 instructions) --
# 0: load x and x_min
instrs.append(grid({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
# 1: dx_total = x - x_min    (RCR of col0 = col1 = x_min)
instrs.append(grid({(0, 0): "SSUB R0, R0, RCR"}))
# 2: index = dx_total >> SHIFT
instrs.append(grid({(0, 0): f"SRT R1, R0, {SHIFT}"}))
# 3: dx = dx_total & mask  (parallel with offset = index * stride on row 1)
instrs.append(grid({(0, 0): f"LAND R0, R0, {mask}", (1, 0): f"SMUL R0, RCT, {stride}"}))
# 4: addr of c[ORDER] (row1), base address (row2, for Horner coeff loading)
instrs.append(
    grid(
        {
            (1, 0): f"SADD R1, R0, {LUT_BASE + ORDER * 4}",
            (2, 0): f"SADD R0, RCT, {LUT_BASE}",
        }
    )
)
# 5: load highest-order coefficient into accumulator
instrs.append(grid({(1, 0): "LWI R1, R1"}))

# -- Horner loop: for k = ORDER-1 down to 0 --
# Each step: acc = (acc * dx) >> SHIFT + c[k]
# 3 instructions per step, with coefficient loading overlapped.
for k in range(ORDER - 1, -1, -1):
    # multiply accumulator by dx, compute address of c[k]
    instrs.append(grid({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k * 4}"}))
    # arithmetic shift right, load c[k]
    instrs.append(grid({(1, 0): f"SRA R1, R1, {SHIFT}", (2, 0): "LWI R1, ROUT"}))
    # add coefficient   (RCB of row1 = row2 = loaded c[k])
    instrs.append(grid({(1, 0): "SADD R1, R1, RCB"}))

# -- Store result and exit --
instrs.append(grid({(1, 0): "SWD R1", (0, 3): "EXIT"}))

with open(f"{KERNEL}/instructions.csv", "w", newline="") as f:
    w = csv.writer(f)
    for t, g in enumerate(instrs):
        w.writerow([t])
        for row in g:
            w.writerow(row)

import numpy as np
import csv
import os
import sys
import math
import argparse
import json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
Q15 = 2**15  # 32768
WORD_SIZE = 4  # bytes per memory word

# Memory map (byte addresses):
ADDR_X = 0  # input x  (Q15)
ADDR_XMIN = 4  # x_min    (Q15)
LUT_BASE = 100  # start of coefficient table
OUTPUT_ADDR = 10000  # where the result is stored


# ---------------------------------------------------------------------------
# Fixed-point helpers
# ---------------------------------------------------------------------------
def float_to_q15(v):
    """Convert float -> Q15 int (saturating to int32 range)."""
    raw = int(round(v * Q15))
    return max(-(2**31), min(2**31 - 1, raw))


def q15_to_float(v):
    return v / Q15


# ---------------------------------------------------------------------------
# LUT generation
# ---------------------------------------------------------------------------
def generate_lut(func, x_min, x_max, shift, order):
    """
    Build the piecewise polynomial lookup table.

    Returns
    -------
    segments : list of dict
    n_seg    : int
    step_q15 : int
    """
    step_q15 = 1 << shift
    step_real = step_q15 / Q15

    x_min_q15 = float_to_q15(x_min)
    x_max_q15 = float_to_q15(x_max)

    n_seg = int((x_max_q15 - x_min_q15) // step_q15)
    if n_seg < 1:
        raise ValueError("Range too small for chosen SHIFT -- try a smaller value.")

    segments = []
    for i in range(n_seg):
        x_start = x_min + i * step_real

        # Sample order+1 equally-spaced points inside the segment
        x_pts = [x_start + j * step_real / max(order, 1) for j in range(order + 1)]
        y_pts = [func(x) for x in x_pts]

        # Polynomial fit in local variable dx = x - x_start
        dx_pts = [x - x_start for x in x_pts]
        coeffs = np.polyfit(dx_pts, y_pts, order)[::-1]  # coeffs[k] -> dx^k

        coeffs_q15 = [float_to_q15(c) for c in coeffs]

        segments.append(
            dict(
                index=i,
                x_start=x_start,
                x_start_q15=x_min_q15 + i * step_q15,
                coeffs_real=list(coeffs),
                coeffs_q15=coeffs_q15,
            )
        )

    return segments, n_seg, step_q15


# ---------------------------------------------------------------------------
# Memory file
# ---------------------------------------------------------------------------
def write_memory(kernel_dir, x_test, x_min, segments, order, version=""):
    """Write memory.csv with the input value and the coefficient LUT."""
    rows = [["Address", "Data"]]

    rows.append([ADDR_X, float_to_q15(x_test)])
    rows.append([ADDR_XMIN, float_to_q15(x_min)])

    n_coeffs = order + 1
    for seg in segments:
        for k in range(n_coeffs):
            addr = LUT_BASE + seg["index"] * n_coeffs * WORD_SIZE + k * WORD_SIZE
            rows.append([addr, seg["coeffs_q15"][k]])

    fpath = os.path.join(kernel_dir, f"memory{version}.csv")
    with open(fpath, "w", newline="") as f:
        writer = csv.writer(f)
        for r in rows:
            writer.writerow(r)
    return fpath


# ---------------------------------------------------------------------------
# Instruction file -- general order (Horner's method on PE(0,0))
# ---------------------------------------------------------------------------
def _nop4():
    return ["NOP", "NOP", "NOP", "NOP"]


def write_instructions(kernel_dir, shift, order, version=""):
    """
    Generate instructions.csv for a polynomial of any order.

    PE(0,0) register plan:
        R0  - x (loaded first), later scratch for loading coefficients
        R1  - x_min, then index, then Horner accumulator
        R2  - base_offset into LUT (kept throughout Horner)
        R3  - dx (kept throughout Horner)

    Execution flow:
        Phase 1: Load x, x_min -> compute index, dx, base_offset
        Phase 2: Horner's method using FXPMUL (Q15 multiply)
        Phase 3: Store result, EXIT
    """
    n_coeffs = order + 1
    bytes_per_segment = n_coeffs * WORD_SIZE

    instrs = []

    def emit(rows):
        t = len(instrs)
        instrs.append((t, rows))

    def op0(s):
        return [s, "NOP", "NOP", "NOP"]

    # ---- Phase 1: Load x and x_min, compute index/dx ----
    emit([op0("LWD R0"), _nop4(), _nop4(), _nop4()])  # R0 = x
    emit([op0("LWD R1"), _nop4(), _nop4(), _nop4()])  # R1 = x_min
    emit([op0("SSUB R2, R0, R1"), _nop4(), _nop4(), _nop4()])  # R2 = x - x_min
    emit([op0(f"SRT R1, R2, {shift}"), _nop4(), _nop4(), _nop4()])  # R1 = index
    emit([op0(f"SLT R3, R1, {shift}"), _nop4(), _nop4(), _nop4()])  # R3 = index<<shift
    emit([op0("SSUB R3, R2, R3"), _nop4(), _nop4(), _nop4()])  # R3 = dx (Q15)
    emit(
        [op0(f"SMUL R2, R1, {bytes_per_segment}"), _nop4(), _nop4(), _nop4()]
    )  # R2=offset

    # ---- Phase 2: Horner evaluation ----
    # Load c[order] (highest order coefficient) into R1 (accumulator)
    c_hi_off = order * WORD_SIZE
    emit([op0(f"SADD R1, R2, {LUT_BASE + c_hi_off}"), _nop4(), _nop4(), _nop4()])
    emit([op0("LWI R1, R1"), _nop4(), _nop4(), _nop4()])

    # Horner loop: for k = order-1 down to 0
    #   acc = FXPMUL(acc, dx) + c[k]
    for k in range(order - 1, -1, -1):
        emit([op0("FXPMUL R1, R1, R3"), _nop4(), _nop4(), _nop4()])
        c_off = k * WORD_SIZE
        emit([op0(f"SADD R0, R2, {LUT_BASE + c_off}"), _nop4(), _nop4(), _nop4()])
        emit([op0("LWI R0, R0"), _nop4(), _nop4(), _nop4()])
        emit([op0("SADD R1, R1, R0"), _nop4(), _nop4(), _nop4()])

    # ---- Phase 3: Store & exit ----
    emit([["SWD R1", "NOP", "NOP", "EXIT"], _nop4(), _nop4(), _nop4()])

    fpath = os.path.join(kernel_dir, f"instructions{version}.csv")
    with open(fpath, "w", newline="") as f:
        writer = csv.writer(f)
        for t, rows in instrs:
            writer.writerow([t])
            for row in rows:
                writer.writerow(row)
    return fpath, len(instrs)

# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
def generate_all(
    func=math.sin,
    func_name="sin",
    x_min=0.0,
    x_max=2 * math.pi,
    shift=13,
    order=1,
    x_test=1.0,
    kernel_name="sine_approx",
    version="",
):
    """
    One-call generator: produces instructions.csv, memory.csv, and notebook.
    """
    os.makedirs(kernel_name, exist_ok=True)

    segments, n_seg, step_q15 = generate_lut(func, x_min, x_max, shift, order)

    order_name = {1: "linear", 2: "quadratic", 3: "cubic"}.get(order, f"degree-{order}")
    print(f"{'='*60}")
    print(f"  ESL-CGRA Piecewise Polynomial LUT Generator")
    print(f"{'='*60}")
    print(f"  Function      : {func_name}(x)")
    print(f"  Range         : [{x_min:.4f}, {x_max:.4f}]")
    print(f"  Order         : {order}  ({order_name})")
    print(f"  SHIFT         : {shift}  ->  step = {step_q15} Q15 = {step_q15/Q15:.6f}")
    print(f"  Segments      : {n_seg}")
    print(f"  Coeffs/seg    : {order+1}")
    print(f"  LUT words     : {n_seg*(order+1)}")
    print(f"  Test point    : x = {x_test}")
    print(f"  Expected      : {func(x_test):.10f}")
    print(f"{'='*60}")

    mem_path = write_memory(kernel_name, x_test, x_min, segments, order, version)
    instr_path, n_instrs = write_instructions(kernel_name, shift, order, version)

    print(f"\n  Generated files:")
    print(f"    {mem_path:<45} ({n_seg*(order+1)+2} memory words)")
    print(f"    {instr_path:<45} ({n_instrs} instructions)")

    # ---- Pure-Python self-check ----
    x_q15 = float_to_q15(x_test)
    xmin_q15 = float_to_q15(x_min)
    dx_total = x_q15 - xmin_q15
    index = dx_total >> shift
    xi_off = index << shift
    dx = dx_total - xi_off

    if 0 <= index < n_seg:
        seg = segments[index]
        acc = seg["coeffs_q15"][order]
        for k in range(order - 1, -1, -1):
            acc = ((acc * dx) >> 15) + seg["coeffs_q15"][k]
        expected = func(x_test)
        print(f"\n  Self-check (Q15 Horner):")
        print(f"    Segment  : {index}  (dx = {dx})")
        print(f"    Result   : {acc} Q15 = {acc/Q15:.10f}")
        print(f"    Expected : {expected:.10f}")
        print(f"    Error    : {abs(acc/Q15 - expected):.2e}")
    else:
        print(f"\n  WARNING: x_test out of range (index={index}, n_seg={n_seg})")

    return kernel_name


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Generate CGRA sine LUT files")
    p.add_argument("--func", default="sin", help="Function: sin, cos")
    p.add_argument("--x_min", type=float, default=0.0)
    p.add_argument("--x_max", type=float, default=2 * math.pi)
    p.add_argument(
        "--shift",
        type=int,
        default=13,
        help="log2(segment width in Q15). Smaller = more accurate.",
    )
    p.add_argument(
        "--order",
        type=int,
        default=1,
        help="Polynomial order: 1=linear, 2=quadratic, 3=cubic, ...",
    )
    p.add_argument(
        "--x_test", type=float, default=1.0, help="Test point to embed in memory"
    )
    p.add_argument("--kernel", default="sine_approx", help="Kernel directory name")
    p.add_argument("--version", default="")

    args = p.parse_args()

    func_map = {"sin": (math.sin, "sin"), "cos": (math.cos, "cos")}
    func, func_name = func_map.get(args.func, (math.sin, "sin"))

    generate_all(
        func=func,
        func_name=func_name,
        x_min=args.x_min,
        x_max=args.x_max,
        shift=args.shift,
        order=args.order,
        x_test=args.x_test,
        kernel_name=args.kernel,
        version=args.version,
    )

# ---- Print summary ----
print(
    f"ORDER={ORDER}, SHIFT={SHIFT}, segments={n_segs}, "
    f"instructions={len(instrs)}, LUT words={n_segs * n_coeffs}"
)
print(f"Files: {KERNEL}/instructions.csv, {KERNEL}/memory.csv, {KERNEL}/sine_lut.ipynb")

# ---- Self-check ----
dx_total = x_test_int - x_min_int
index = dx_total >> SHIFT
dx = dx_total & mask
seg = segments[index]
acc = seg[ORDER]
for k in range(ORDER - 1, -1, -1):
    acc = (acc * dx >> SHIFT) + seg[k]
expected = round(func(X_TEST) * SCALE)
print(
    f"x={X_TEST} -> index={index}, dx={dx}, result={acc}, expected={expected}, "
    f"error={abs(acc - expected)/SCALE:.2e}"
)
