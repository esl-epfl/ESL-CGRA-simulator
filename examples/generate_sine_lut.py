#!/usr/bin/env python3
"""
=============================================================================
  ESL-CGRA Sine Approximation Generator
=============================================================================

Generates all files needed to run a piecewise polynomial approximation of
sin(x) (or any function) on the ESL-CGRA simulator.

Algorithm (piecewise polynomial with Horner evaluation):
  1. Divide [x_min, x_max] into N segments of width 2^SHIFT (Q15 fixed-point).
  2. For each segment, fit a polynomial of the requested order.
  3. At runtime on the CGRA:
       a. Load x (Q15 fixed-point)
       b. Compute segment index = (x - x_min) >> SHIFT
       c. Compute dx = x - x_segment_start
       d. Evaluate polynomial via Horner's method:
            y = (...((c[K]*dx + c[K-1])*dx + ...)*dx + c[0])   using FXPMUL
       e. Store y

Fixed-point: Q15  (real_value = int_value / 32768)

NOTE: The simulator's cgra.py needs `from ctypes import c_int32, c_int64`
      (the original only imports c_int32, but FXPMUL uses c_int64).

Usage:
    python generate_sine_lut.py                          # defaults: linear
    python generate_sine_lut.py --order 2 --shift 11     # quadratic, finer
    python generate_sine_lut.py --order 3 --x_test 1.5   # cubic

Outputs (in <kernel_dir>/):
    instructions.csv   -- CGRA instruction file
    memory.csv         -- memory initialisation (LUT + input)
    sine_lut.ipynb     -- Jupyter notebook to run & validate
"""

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
# Jupyter notebook generator
# ---------------------------------------------------------------------------
def write_notebook(
    kernel_dir, kernel_name, x_test, x_min, x_max, shift, order, func_name, version=""
):
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python", "version": "3.12.0"},
        },
        "cells": [],
    }

    def md(src):
        nb["cells"].append({"cell_type": "markdown", "metadata": {}, "source": src})

    def code(src):
        nb["cells"].append(
            {
                "cell_type": "code",
                "metadata": {},
                "outputs": [],
                "source": src,
                "execution_count": None,
            }
        )

    order_name = {1: "linear", 2: "quadratic", 3: "cubic"}.get(order, f"degree-{order}")
    md(
        [
            f"# Piecewise Polynomial Sine on ESL-CGRA\n",
            f"\n",
            f"| Parameter | Value |\n",
            f"|-----------|-------|\n",
            f"| Function | `{func_name}(x)` |\n",
            f"| Range | [{x_min:.4f}, {x_max:.4f}] |\n",
            f"| Order | {order} ({order_name}) |\n",
            f"| SHIFT | {shift} (segment width = {(1<<shift)/Q15:.6f} rad) |\n",
            f"| Test point | x = {x_test} |\n",
            f"| Expected | {func_name}({x_test}) = {math.sin(x_test):.10f} |\n",
        ]
    )

    md(
        [
            "## 1. Run the CGRA simulation\n",
            "\n",
            "**Important**: `cgra.py` needs this import for FXPMUL to work:\n",
            "```python\n",
            "from ctypes import c_int32, c_int64\n",
            "```\n",
        ]
    )

    code(
        [
            "import sys, os, csv, math\n",
            "\n",
            "# Point to simulator sources (adjust as needed)\n",
            "SIM_SRC = os.path.abspath('..')\n",
            "sys.path.insert(0, SIM_SRC)\n",
            "sys.path.insert(0, '.')\n",
            "from cgra import *\n",
            "\n",
            f'KERNEL  = "{kernel_name}"\n',
            f'VERSION = "{version}"\n',
            f"Q15     = {Q15}\n",
            "\n",
            "load_addrs  = [0, 0, 0, 0]\n",
            "store_addrs = [10000, 0, 0, 0]\n",
            "\n",
            "run(KERNEL, version=VERSION,\n",
            '    pr=["ROUT", "OPS", "R0", "R1", "R2", "R3", "ALL_LAT_INFO", "ALL_PWR_EN_INFO"],\n',
            "    load_addrs=load_addrs, store_addrs=store_addrs, limit=500)\n",
        ]
    )

    md(["## 2. Read result and compare"])

    code(
        [
            f'mem_path = os.path.join(KERNEL, "memory_out" + VERSION + ".csv")\n',
            "with open(mem_path) as f:\n",
            "    mem_out = {int(r[0]): int(r[1]) for r in csv.reader(f)}\n",
            "\n",
            f"x_test   = {x_test}\n",
            "result   = mem_out.get(10000)\n",
            "expected = math.sin(x_test)\n",
            "\n",
            "print(f'Q15 integer  : {result}')\n",
            "print(f'Float result : {result/Q15:.10f}')\n",
            "print(f'Expected     : {expected:.10f}')\n",
            "print(f'Abs error    : {abs(result/Q15 - expected):.2e}')\n",
        ]
    )

    md(["## 3. Sweep the full range"])

    code(
        [
            "import numpy as np\n",
            "sys.path.insert(0, '.')\n",
            "import generate_sine_lut as gen\n",
            "\n",
            f"X_MIN, X_MAX = {x_min}, {x_max}\n",
            f"SHIFT, ORDER = {shift}, {order}\n",
            "\n",
            "segments, n_seg, step_q15 = gen.generate_lut(math.sin, X_MIN, X_MAX, SHIFT, ORDER)\n",
            "\n",
            "xs = np.linspace(X_MIN + 0.001, X_MAX - 0.001, 80)\n",
            "results, expecteds = [], []\n",
            "\n",
            "for xt in xs:\n",
            "    gen.write_memory(KERNEL, xt, X_MIN, segments, ORDER, version=VERSION)\n",
            "    run(KERNEL, version=VERSION, pr=[], load_addrs=[0,0,0,0],\n",
            "        store_addrs=[10000,0,0,0], limit=500)\n",
            f'    with open(os.path.join(KERNEL, "memory_out" + VERSION + ".csv")) as f:\n',
            "        mo = {int(r[0]): int(r[1]) for r in csv.reader(f)}\n",
            "    val = mo.get(10000)\n",
            "    results.append(val / Q15 if val is not None else float('nan'))\n",
            "    expecteds.append(math.sin(xt))\n",
            "\n",
            "results   = np.array(results)\n",
            "expecteds = np.array(expecteds)\n",
            "errors    = np.abs(results - expecteds)\n",
            "\n",
            "print(f'Points tested  : {len(xs)}')\n",
            "print(f'Max abs error  : {np.nanmax(errors):.6e}')\n",
            "print(f'Mean abs error : {np.nanmean(errors):.6e}')\n",
        ]
    )

    md(["## 4. Plot results"])

    code(
        [
            "try:\n",
            "    import matplotlib.pyplot as plt\n",
            "    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)\n",
            "    ax1.plot(xs, expecteds, 'b-', lw=2, label='sin(x) exact')\n",
            f"    ax1.plot(xs, results, 'r--', lw=1.5, label='CGRA order-{order}')\n",
            "    ax1.legend(); ax1.set_ylabel('Value'); ax1.grid(True, alpha=0.3)\n",
            f"    ax1.set_title('Piecewise order-{order} sine on ESL-CGRA')\n",
            "    ax2.semilogy(xs, errors, 'k-')\n",
            "    ax2.set_ylabel('Abs error'); ax2.set_xlabel('x (rad)'); ax2.grid(True, alpha=0.3)\n",
            "    plt.tight_layout()\n",
            "    plt.savefig(os.path.join(KERNEL, 'accuracy.png'), dpi=150); plt.show()\n",
            "except ImportError:\n",
            "    print('matplotlib not available')\n",
        ]
    )

    md(
        [
            "## 5. Regenerate with different parameters\n",
            "\n",
            "Uncomment and edit to try a different configuration:",
        ]
    )

    code(
        [
            "# import generate_sine_lut as gen\n",
            "# gen.generate_all(\n",
            "#     func=math.sin, func_name='sin',\n",
            "#     x_min=0.0, x_max=2*math.pi,\n",
            "#     shift=11,    # finer segments (more accuracy)\n",
            "#     order=2,     # quadratic\n",
            "#     x_test=1.5,\n",
            f"#     kernel_name='{kernel_name}',\n",
            "# )\n",
        ]
    )

    fpath = os.path.join(kernel_dir, f"sine_lut{version}.ipynb")
    with open(fpath, "w") as f:
        json.dump(nb, f, indent=1)
    return fpath


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
    nb_path = write_notebook(
        kernel_name, kernel_name, x_test, x_min, x_max, shift, order, func_name, version
    )

    print(f"\n  Generated files:")
    print(f"    {mem_path:<45} ({n_seg*(order+1)+2} memory words)")
    print(f"    {instr_path:<45} ({n_instrs} instructions)")
    print(f"    {nb_path}")

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
