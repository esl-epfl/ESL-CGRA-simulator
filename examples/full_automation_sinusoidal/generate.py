"""
CGRA Sine — Pareto Variant Generator (v3)
==========================================
13 architecture variants exploring 3 axes independently:
  Pipeline depth — how many PEs, how overlapped
  LUT coverage   — full/half/quarter wave symmetry
  Throughput     — 1×/2×/4× parallel evaluations

Key optimization for ORDER=3: stride = 16 = 2^4, so the offset
multiply (SMUL, 3CC) can be replaced with a shift (SLT, 1CC).

Usage:  python generate.py [--order 3] [--shifts 8 9 10 11 12]
"""

import math, csv, os, json, argparse
import numpy as np


# ── Params ─────────────────────────────────────────────────────────
def func(x):
    return math.sin(x)


SCALE = 10000
X_MIN = 0.0
X_MAX = 2 * math.pi
# X_TE1ST = 5.0
# where in memory my LUT starts
LUT_BASE = 100
N_ROWS, N_COLS = 4, 4
OP_LAT = {
    "NOP": 1,
    "EXIT": 2,
    "SADD": 1,
    "SSUB": 1,
    "SLT": 1,
    "SRT": 1,
    "SRA": 1,
    "LAND": 1,
    "LOR": 1,
    "LXOR": 1,
    "SMUL": 3,
    "FXPMUL": 3,
    "BSFA": 1,
    "BZFA": 1,
    "BEQ": 1,
    "BNE": 1,
    "BLT": 1,
    "BGE": 1,
    "JUMP": 1,
    "LWD": 2,
    "SWD": 2,
    "LWI": 2,
    "SWI": 2,
    "LNAND": 1,
    "LNOR": 1,
    "LXNOR": 1,
}
#######################################################################
############################ Helpers ##################################
#######################################################################


def derived(O, S, xmin=X_MIN, xmax=X_MAX):
    """
    Finds some key values needed by the tool

    Inputs:
        O = order
        S = SHIFT

    Outputs:
        xmi = fixed point minimum
        xma = fixed point maximum
        w = segment width in fixed point units
        mask = mask to extract local offset in segment
        n = number of full segments
        nc = number of coefficients per segment
        stride = bytes per segment in memory
    """

    xmi = round(xmin * SCALE)
    xma = round(xmax * SCALE)
    w = 1 << S
    mask = w - 1
    n = (xma - xmi) >> S
    nc = O + 1
    stride = nc * 4

    return xmi, xma, w, mask, n, nc, stride


def fit_segs(O, S, xmin=X_MIN, xmax=X_MAX):
    """
    Creates the piecewise polynomial coefficients. For each segment it
        1. picks segment start x0
        2. samples sin(x) at O+1 points over the segment
        3. fits a degree-O polynomial using np.polyfit
        4. stores coeff scaled by SCALE
    """
    xmi = round(xmin * SCALE)
    xma = round(xmax * SCALE)
    w = 1 << S

    n = (xma - xmi) >> S
    segs = []
    for i in range(n):
        x0 = xmin + i * w / SCALE
        ts = [j / max(O, 1) for j in range(O + 1)]
        ys = [func(x0 + t * w / SCALE) for t in ts]
        segs.append([round(c * SCALE) for c in np.polyfit(ts, ys, O)[::-1]])
    return segs, n


def G(ops):
    """
    Makes one 4x4 instruction grid
    """
    g = [["NOP"] * N_COLS for _ in range(N_ROWS)]
    for (r, c), op in ops.items():
        g[r][c] = op
    return g


def hcheck(xt, O, S, segs, xmi):
    w, m = 1 << S, (1 << S) - 1
    xi = round(xt * SCALE)
    dt = xi - xmi
    idx = dt >> S
    dx = dt & m
    if idx < 0 or idx >= len(segs):
        return None, None, None
    s = segs[idx]
    acc = s[O]
    for k in range(O - 1, -1, -1):
        acc = (acc * dx >> S) + s[k]
    return acc, round(func(xt) * SCALE), abs(acc - round(func(xt) * SCALE)) / SCALE


def mem_lut(segs, stride, inputs):
    """
    Builds memory as:
        1. input values you want at fixed addresses
        2. then all segment coeff in sequence starting at LUT_BASE

        xt addr 0
        xmi addr 4
        LUT coeff addr >=100
    """
    m = list(inputs)
    for i, cs in enumerate(segs):
        for k, c in enumerate(cs):
            m.append((LUT_BASE + i * stride + k * 4, c))
    return m


def tlat(I):
    return sum(
        max(OP_LAT.get(op.replace(",", " ").split()[0], 1) for row in g for op in row)
        for g in I
    )


def tlat_loop(I, loop):
    if not loop:
        return tlat(I)
    s, e, n = loop
    t = 0
    for i, g in enumerate(I):
        mx = max(
            OP_LAT.get(op.replace(",", " ").split()[0], 1) for row in g for op in row
        )
        t += mx * (n if s <= i <= e else 1)
    return t


def apes(I):
    return len(
        {
            (r, c)
            for g in I
            for r in range(N_ROWS)
            for c in range(N_COLS)
            if g[r][c] != "NOP"
        }
    )


def pei(I):
    return sum(
        1 for g in I for r in range(N_ROWS) for c in range(N_COLS) if g[r][c] != "NOP"
    )


def stride_op(ORDER, stride):
    """Use SLT (1CC) if stride is power-of-2, else SMUL (3CC)."""
    if stride > 0 and (stride & (stride - 1)) == 0:
        shift_amt = stride.bit_length() - 1
        return f"SLT R0, RCT, {shift_amt}"
    return f"SMUL R0, RCT, {stride}"


def write(name, O, S, I, mem, segs, extra=None):
    tag = f"{name}_T{O}_S{S}"
    d = os.path.join("pareto_out", tag)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "instructions.csv"), "w", newline="") as f:
        w = csv.writer(f)
        for t, g in enumerate(I):
            w.writerow([t])
            [w.writerow(row) for row in g]
    with open(os.path.join(d, "memory.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Address", "Data"])
        [w.writerow([a, v]) for a, v in mem]
    loop = (extra or {}).get("_loop")
    lat = tlat_loop(I, loop)
    ex = extra or {}
    m = {
        "variant": name,
        "tag": tag,
        "order": O,
        "shift": S,
        "n_instructions": len(I),
        "total_latency_cc": lat,
        "active_pes": apes(I),
        "pe_instructions": pei(I),
        "lut_words": ex.get("lut_words_override", len(segs) * (O + 1) if segs else 0),
        "n_segments": ex.get("n_segments_override", len(segs) if segs else 0),
        "axis": ex.get("axis", ""),
        "throughput_factor": ex.get("throughput_factor", 1),
    }
    with open(os.path.join(d, "metrics.json"), "w") as f:
        json.dump(m, f, indent=2)
    return m


def chk(name, O, S, acc, exp, err):
    print(
        f"  {name:<14} T{O} S{S}: {acc} exp={exp} err={err:.2e}"
        if acc
        else f"  {name:<14} T{O} S{S}: CHECK FAILED"
    )


# ══════════════════════════════════════════════════════════════════
#  AXIS 1: PIPELINE DEPTH (full wave, varying PE count & speed)
# ══════════════════════════════════════════════════════════════════


def gen_SEQ(O, S, x_test):
    """1 compute PE. Absolute minimum resources"""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(x_test * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0"}))
    I.append(G({(0, 0): "LWD R1"}))
    I.append(G({(0, 0): "SSUB R0, R0, R1"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}"}))
    I.append(G({(0, 0): f"SMUL R1, R1, {stride}"}))
    I.append(G({(0, 0): f"SADD R1, R1, {LUT_BASE}"}))
    I.append(G({(0, 0): f"SADD R3, R1, {O*4}"}))
    I.append(G({(0, 0): "LWI R2, R3"}))
    for k in range(O - 1, -1, -1):
        I.append(G({(0, 0): "SMUL R2, R2, R0"}))
        I.append(G({(0, 0): f"SRA R2, R2, {S}"}))
        I.append(G({(0, 0): f"SADD R3, R1, {k*4}"}))
        I.append(G({(0, 0): "LWI R3, R3"}))
        I.append(G({(0, 0): "SADD R2, R2, R3"}))
    I.append(G({(0, 0): "SWD R2", (0, 3): "EXIT"}))
    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("SEQ", O, S, a, e, err)
    return write(
        "SEQ",
        O,
        S,
        I,
        mem_lut(segs, stride, [(0, xt), (4, xmi)]),
        segs,
        {
            "axis": "pipeline",
            "load_addrs": [0, 0, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
        },
    )


def gen_PIPE2(O, S, x_test):
    """2 compute PEs. PE(0,0)=dx holder, PE(1,0)=everything else"""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(x_test * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): stride_op(O, stride)}))
    I.append(G({(1, 0): f"SADD R0, R0, {LUT_BASE}"}))
    I.append(G({(1, 0): f"SADD R1, R0, {O*4}"}))
    I.append(G({(1, 0): "LWI R2, R1"}))
    for k in range(O - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R2, R2, RCT"}))
        I.append(G({(1, 0): f"SRA R2, R2, {S}"}))
        I.append(G({(1, 0): f"SADD R1, R0, {k*4}"}))
        I.append(G({(1, 0): "LWI R3, R1"}))
        I.append(G({(1, 0): "SADD R2, R2, R3"}))
    I.append(G({(1, 0): "SWD R2", (0, 3): "EXIT"}))
    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("PIPE2", O, S, a, e, err)
    return write(
        "PIPE2",
        O,
        S,
        I,
        mem_lut(segs, stride, [(0, xt), (4, xmi)]),
        segs,
        {
            "axis": "pipeline",
            "load_addrs": [0, 4, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
        },
    )


def gen_PIPE3(O, S, x_test):
    """3 compute PEs. Overlaps SMUL with coefficient prefetch"""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(x_test * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): stride_op(O, stride)}))
    I.append(
        G({(1, 0): f"SADD R1, R0, {LUT_BASE+O*4}", (2, 0): f"SADD R0, RCT, {LUT_BASE}"})
    )
    I.append(G({(1, 0): "LWI R1, R1"}))
    for k in range(O - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {S}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))
    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))
    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("PIPE3", O, S, a, e, err)
    return write(
        "PIPE3",
        O,
        S,
        I,
        mem_lut(segs, stride, [(0, xt), (4, xmi)]),
        segs,
        {
            "axis": "pipeline",
            "load_addrs": [0, 4, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
        },
    )


def gen_HYBRID(O, S, x_test):
    """3 PEs + immediate c[ORDER]. Skips 1 LWI"""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(x_test * SCALE)
    c_top = segs[(round(x_test * SCALE) - xmi) >> S][O]
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): stride_op(O, stride)}))
    I.append(
        G({(1, 0): f"SADD R1, ZERO, {c_top}", (2, 0): f"SADD R0, RCT, {LUT_BASE}"})
    )
    for k in range(O - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {S}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))
    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))
    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("HYBRID", O, S, a, e, err)
    return write(
        "HYBRID",
        O,
        S,
        I,
        mem_lut(segs, stride, [(0, xt), (4, xmi)]),
        segs,
        {
            "axis": "pipeline",
            "load_addrs": [0, 4, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
        },
    )


def gen_LOOP(O, S, x_test):
    """4 PEs. Looped Horner with BGE. 10 config instrs regardless of ORDER"""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(x_test * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}", (3, 0): f"SADD R0, ZERO, {O-1}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): stride_op(O, stride)}))
    I.append(
        G(
            {
                (1, 0): f"SADD R1, R0, {LUT_BASE+O*4}",
                (2, 0): f"SADD R0, RCT, {LUT_BASE+(O-1)*4}",
            }
        )
    )
    I.append(G({(1, 0): "LWI R1, R1", (2, 0): "SADD ROUT, R0, 0"}))
    LS = len(I)
    I.append(G({(1, 0): "SMUL R1, R1, RCT", (3, 0): "SSUB R0, R0, 1"}))
    I.append(G({(1, 0): f"SRA R1, R1, {S}", (2, 0): "LWI R1, ROUT"}))
    I.append(
        G(
            {
                (1, 0): "SADD R1, R1, RCB",
                (2, 0): "SSUB R0, R0, 4",
                (3, 0): f"BGE R0, ZERO, {LS}",
            }
        )
    )
    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))
    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("LOOP", O, S, a, e, err)
    return write(
        "LOOP",
        O,
        S,
        I,
        mem_lut(segs, stride, [(0, xt), (4, xmi)]),
        segs,
        {
            "axis": "pipeline",
            "_loop": (LS, LS + 2, O),
            "load_addrs": [0, 4, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
        },
    )


def gen_WIDE(O, S, x_test):
    """2-column wide layout.
    PE(0,0)=dx holder, PE(0,1)=offset+base, PE(1,1)=addr+coeff load, PE(1,0)=Horner.
    Functionally similar to PIPE3, but spread across 2 columns instead of 1.
    """
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(x_test * SCALE)

    I = []
    # t0: load x and x_min
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    # t1: dx_total = x - x_min
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    # t2: index
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    # t3: dx on PE(0,0), offset on PE(0,1) using left-neighbor relay
    I.append(
        G(
            {
                (0, 0): f"LAND R0, R0, {mask}",
                (0, 1): stride_op(O, stride).replace("RCT", "RCL"),
            }
        )
    )
    # t4: base on PE(0,1)
    I.append(G({(0, 1): f"SADD R0, R0, {LUT_BASE}"}))
    # t5: copy base into PE(1,1)
    I.append(G({(1, 1): "SADD R0, RCT, 0"}))
    # t6: addr of c[ORDER]
    I.append(G({(1, 1): f"SADD R1, R0, {O*4}"}))
    # t7: load c[ORDER]
    I.append(G({(1, 1): "LWI R1, R1"}))
    # t8: acc = c[ORDER]
    I.append(G({(1, 0): "SADD R1, RCR, 0"}))

    # Horner on PE(1,0), coeff address+load on PE(1,1)
    for k in range(O - 1, -1, -1):
        I.append(
            G(
                {
                    (1, 0): "SMUL R1, R1, RCT",  # RCT = PE(0,0) = dx
                    (1, 1): f"SADD R2, R0, {k*4}",  # addr of c[k], base kept in R0
                }
            )
        )
        I.append(
            G(
                {
                    (1, 0): f"SRA R1, R1, {S}",
                    (1, 1): "LWI R2, R2",
                }
            )
        )
        I.append(G({(1, 0): "SADD R1, R1, RCR"}))  # RCR = PE(1,1) = c[k]

    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))

    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("WIDE", O, S, a, e, err)
    return write(
        "WIDE",
        O,
        S,
        I,
        mem_lut(segs, stride, [(0, xt), (4, xmi)]),
        segs,
        {
            "axis": "pipeline",
            "load_addrs": [0, 4, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
        },
    )


def gen_DENSE(O, S, x_test):
    """Dense layout: 9 PEs across 3 columns. Parallel coefficient address
    computation on row 1 cols 0-2, parallel loading on row 2 cols 0-1.
    Same Horner chain on PE(3,0) but setup is faster by overlapping work.

    Layout:
      Row 0: PE(0,0)=load x, PE(0,1)=load x_min, PE(0,2)=index relay
      Row 1: PE(1,0)=offset+base, PE(1,1)=addr c[ORDER], PE(1,2)=addr c[ORDER-1]
      Row 2: PE(2,0)=load c[ORDER], PE(2,1)=addr+load coefficients
      Row 3: PE(3,0)=Horner accumulator + store
    PE(3,0) reads dx from PE(0,0) via RCB (row 3+1 wraps to row 0).
    PE(3,0) reads coefficients from PE(2,0) via RCT.
    """
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(x_test * SCALE)
    I = []
    # t0: parallel loads
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    # t1: dx_total
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    # t2: index + relay
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    # t3: dx on PE(0,0), offset on PE(1,0) — use SLT if possible
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): stride_op(O, stride)}))
    # t4: base addr + addr of c[ORDER]
    I.append(
        G(
            {
                (1, 0): f"SADD R0, R0, {LUT_BASE}",
                (1, 1): f"SADD R0, RCL, {LUT_BASE+O*4}",
            }
        )
    )

    # t5: load c[ORDER], compute base on PE(2,0)
    I.append(
        G(
            {
                (2, 0): f"SADD R0, RCT, 0",
                (1, 1): "LWI R0, R0",
            }
        )
    )

    # t6: Transfer c[ORDER] to PE(3,0). PE(1,1).old_out = c[ORDER] (from t5 LWI).
    I.append(G({(1, 0): "SADD R1, RCR, 0"}))  # acc = c[ORDER]

    # Horner on PE(1,0), addr+load on PE(2,0)
    for k in range(O - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {S}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))  # RCB=PE(2,0)=c[k] ✓

    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))

    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("DENSE", O, S, a, e, err)
    return write(
        "DENSE",
        O,
        S,
        I,
        mem_lut(segs, stride, [(0, xt), (4, xmi)]),
        segs,
        {
            "axis": "pipeline",
            "load_addrs": [0, 4, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
        },
    )


# ══════════════════════════════════════════════════════════════════
#  AXIS 2: LUT COVERAGE (PIPE3 base, varying memory)
# ══════════════════════════════════════════════════════════════════


def gen_HWAVE(O, S, x_test):
    """Half-wave: LUT for [0,π]. sin(x) = -sin(x-π) for x≥π. Half memory."""
    pi = round(math.pi * SCALE)
    _, _, w, mask, _, nc, stride = derived(O, S, 0.0, math.pi)
    segs, _ = fit_segs(O, S, 0.0, math.pi)
    xt = round(x_test * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 1): "LWD R1"}))
    I.append(G({(1, 0): "SADD R3, ZERO, 1"}))
    I.append(G({(0, 0): "SSUB R1, R0, RCR"}))  # x-pi
    I.append(G({(0, 0): "BSFA R0, R0, R1, SELF", (1, 0): "BSFA R3, R3, ZERO, RCT"}))
    I.append(G({(1, 0): "SADD R3, R3, R3"}))
    I.append(G({(1, 0): "SSUB R3, R3, 1"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): stride_op(O, stride)}))
    I.append(
        G({(1, 0): f"SADD R1, R0, {LUT_BASE+O*4}", (2, 0): f"SADD R0, RCT, {LUT_BASE}"})
    )
    I.append(G({(1, 0): "LWI R1, R1"}))
    for k in range(O - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {S}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))
    I.append(G({(1, 0): "SMUL R1, R1, R3"}))
    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))
    mem = [(0, xt), (4, 0), (8, pi)]
    for i, cs in enumerate(segs):
        for k, c in enumerate(cs):
            mem.append((LUT_BASE + i * stride + k * 4, c))
    x = x_test
    sign = 1
    if x >= math.pi:
        x -= math.pi
        sign = -1
    xi = round(x * SCALE)
    idx = xi >> S
    dx = xi & mask
    if idx >= len(segs):
        idx = len(segs) - 1
    s = segs[idx]
    acc = s[O]
    for kk in range(O - 1, -1, -1):
        acc = (acc * dx >> S) + s[kk]
    acc *= sign
    exp = round(func(x_test) * SCALE)
    chk("HWAVE", O, S, acc, exp, abs(acc - exp) / SCALE)
    return write(
        "HWAVE",
        O,
        S,
        I,
        mem,
        segs,
        {"axis": "memory", "load_addrs": [0, 4, 0, 0], "store_addrs": [10000, 0, 0, 0]},
    )


def gen_QWAVE(O, S, x_test):
    """Quarter-wave: LUT for [0,π/2]. Double fold. 1/4 memory."""
    hpi = round(math.pi / 2 * SCALE)
    pi = round(math.pi * SCALE)
    _, _, w, mask, _, nc, stride = derived(O, S, 0.0, math.pi / 2)
    segs, _ = fit_segs(O, S, 0.0, math.pi / 2)
    xt = round(x_test * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 1): "LWD R1"}))
    I.append(G({(0, 1): "LWD R2"}))
    I.append(G({(1, 0): "SADD R3, ZERO, 1"}))
    I.append(G({(0, 0): "SSUB R1, R0, RCR"}))
    I.append(G({(0, 0): "BSFA R0, R0, R1, SELF", (1, 0): "BSFA R3, R3, ZERO, RCT"}))
    I.append(G({(1, 0): "SADD R3, R3, R3"}))
    I.append(G({(1, 0): "SSUB R3, R3, 1"}))
    I.append(G({(0, 1): "SADD ROUT, R1, 0"}))
    I.append(G({(0, 0): "SSUB R1, R0, RCR"}))
    I.append(G({(0, 0): "SSUB R2, RCR, R1"}))
    I.append(G({(0, 0): "BSFA R0, R0, R2, SELF"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): stride_op(O, stride)}))
    I.append(
        G({(1, 0): f"SADD R1, R0, {LUT_BASE+O*4}", (2, 0): f"SADD R0, RCT, {LUT_BASE}"})
    )
    I.append(G({(1, 0): "LWI R1, R1"}))
    for k in range(O - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {S}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))
    I.append(G({(1, 0): "SMUL R1, R1, R3"}))
    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))
    mem = [(0, xt), (4, 0), (8, hpi), (12, pi)]
    for i, cs in enumerate(segs):
        for k, c in enumerate(cs):
            mem.append((LUT_BASE + i * stride + k * 4, c))
    x = x_test
    sign = 1
    if x >= math.pi:
        x -= math.pi
        sign = -1
    if x >= math.pi / 2:
        x = math.pi - x
    xi = round(x * SCALE)
    idx = xi >> S
    dx = xi & mask
    if idx >= len(segs):
        idx = len(segs) - 1
    s = segs[idx]
    acc = s[O]
    for kk in range(O - 1, -1, -1):
        acc = (acc * dx >> S) + s[kk]
    acc *= sign
    exp = round(func(x_test) * SCALE)
    chk("QWAVE", O, S, acc, exp, abs(acc - exp) / SCALE)
    return write(
        "QWAVE",
        O,
        S,
        I,
        mem,
        segs,
        {"axis": "memory", "load_addrs": [0, 4, 0, 0], "store_addrs": [10000, 0, 0, 0]},
    )


# ══════════════════════════════════════════════════════════════════
#  AXIS 3: THROUGHPUT (PIPE3 base, varying parallelism)
# ══════════════════════════════════════════════════════════════════


def gen_DUAL(O, S, x_test):
    """2× throughput: two PIPE3 datapaths on columns 0 and 2."""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(x_test * SCALE)
    xt2 = round(2.0 * SCALE)
    I = []
    I.append(
        G({(0, 0): "LWD R0", (0, 1): "LWD R0", (0, 2): "LWD R0", (0, 3): "LWD R0"})
    )
    I.append(G({(0, 0): "SSUB R0, R0, RCR", (0, 2): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}", (0, 2): f"SRT R1, R0, {S}"}))
    sop = stride_op(O, stride)
    I.append(
        G(
            {
                (0, 0): f"LAND R0, R0, {mask}",
                (1, 0): sop,
                (0, 2): f"LAND R0, R0, {mask}",
                (1, 2): sop,
            }
        )
    )
    I.append(
        G(
            {
                (1, 0): f"SADD R1, R0, {LUT_BASE+O*4}",
                (2, 0): f"SADD R0, RCT, {LUT_BASE}",
                (1, 2): f"SADD R1, R0, {LUT_BASE+O*4}",
                (2, 2): f"SADD R0, RCT, {LUT_BASE}",
            }
        )
    )
    I.append(G({(1, 0): "LWI R1, R1", (1, 2): "LWI R1, R1"}))
    for k in range(O - 1, -1, -1):
        I.append(
            G(
                {
                    (1, 0): "SMUL R1, R1, RCT",
                    (2, 0): f"SADD ROUT, R0, {k*4}",
                    (1, 2): "SMUL R1, R1, RCT",
                    (2, 2): f"SADD ROUT, R0, {k*4}",
                }
            )
        )
        I.append(
            G(
                {
                    (1, 0): f"SRA R1, R1, {S}",
                    (2, 0): "LWI R1, ROUT",
                    (1, 2): f"SRA R1, R1, {S}",
                    (2, 2): "LWI R1, ROUT",
                }
            )
        )
        I.append(G({(1, 0): "SADD R1, R1, RCB", (1, 2): "SADD R1, R1, RCB"}))
    I.append(G({(1, 0): "SWD R1", (1, 2): "SWD R1", (3, 3): "EXIT"}))
    mem = [(0, xt), (4, xmi), (8, xt2), (12, xmi)]
    for i, cs in enumerate(segs):
        for k, c in enumerate(cs):
            mem.append((LUT_BASE + i * stride + k * 4, c))
    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("DUAL", O, S, a, e, err)
    return write(
        "DUAL",
        O,
        S,
        I,
        mem,
        segs,
        {
            "axis": "throughput",
            "throughput_factor": 2,
            "load_addrs": [0, 4, 8, 12],
            "store_addrs": [10000, 0, 10004, 0],
        },
    )


def gen_QUAD(O, S, x_test):
    """4× throughput: four PIPE3 datapaths, one per column."""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xvals = [round(v * SCALE) for v in [1.0, 2.0, 3.0, 5.0]]
    sop = stride_op(O, stride)
    I = []
    I.append(G({(0, c): "LWD R0" for c in range(4)}))
    I.append(G({(0, c): "LWD R1" for c in range(4)}))
    I.append(G({(0, c): "SSUB R0, R0, R1" for c in range(4)}))
    I.append(G({(0, c): f"SRT R1, R0, {S}" for c in range(4)}))
    o = {}
    for c in range(4):
        o[(0, c)] = f"LAND R0, R0, {mask}"
        o[(1, c)] = sop.replace("RCT", "RCT")
    I.append(G(o))
    o = {}
    for c in range(4):
        o[(1, c)] = f"SADD R1, R0, {LUT_BASE+O*4}"
        o[(2, c)] = f"SADD R0, RCT, {LUT_BASE}"
    I.append(G(o))
    I.append(G({(1, c): "LWI R1, R1" for c in range(4)}))
    for k in range(O - 1, -1, -1):
        oa, ob, oc = {}, {}, {}
        for c in range(4):
            oa[(1, c)] = "SMUL R1, R1, RCT"
            oa[(2, c)] = f"SADD ROUT, R0, {k*4}"
        I.append(G(oa))
        for c in range(4):
            ob[(1, c)] = f"SRA R1, R1, {S}"
            ob[(2, c)] = "LWI R1, ROUT"
        I.append(G(ob))
        for c in range(4):
            oc[(1, c)] = "SADD R1, R1, RCB"
        I.append(G(oc))
    oe = {c: "SWD R1" for c in range(4)}
    oe2 = {(1, c): "SWD R1" for c in range(4)}
    oe2[(3, 3)] = "EXIT"
    I.append(G(oe2))
    mem = []
    for c in range(4):
        mem.append((c * 8, xvals[c]))
        mem.append((c * 8 + 4, xmi))
    for i, cs in enumerate(segs):
        for k, cv in enumerate(cs):
            mem.append((LUT_BASE + i * stride + k * 4, cv))
    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("QUAD", O, S, a, e, err)
    return write(
        "QUAD",
        O,
        S,
        I,
        mem,
        segs,
        {
            "axis": "throughput",
            "throughput_factor": 4,
            "load_addrs": [0, 8, 16, 24],
            "store_addrs": [10000, 10004, 10008, 10012],
        },
    )


def gen_STAGGERED_QUAD(O, S, x_test):
    """4× throughput with staggered launches.
    One PIPE3-style lane per column, but column c starts at cycle c.
    Goal: denser occupancy / more solid dataflow block than gen_QUAD.
    """
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xvals = [round(v * SCALE) for v in [1.0, 2.0, 3.0, 5.0]]
    sop = stride_op(O, stride)

    # Per-column microprogram = QUAD lane, but expressed as per-time op dicts
    lane = []
    lane.append(lambda c: {(0, c): "LWD R0"})
    lane.append(lambda c: {(0, c): "LWD R1"})
    lane.append(lambda c: {(0, c): "SSUB R0, R0, R1"})
    lane.append(lambda c: {(0, c): f"SRT R1, R0, {S}"})
    lane.append(lambda c: {(0, c): f"LAND R0, R0, {mask}", (1, c): sop})
    lane.append(
        lambda c: {
            (1, c): f"SADD R1, R0, {LUT_BASE+O*4}",
            (2, c): f"SADD R0, RCT, {LUT_BASE}",
        }
    )
    lane.append(lambda c: {(1, c): "LWI R1, R1"})
    for k in range(O - 1, -1, -1):
        lane.append(
            lambda c, k=k: {
                (1, c): "SMUL R1, R1, RCT",
                (2, c): f"SADD ROUT, R0, {k*4}",
            }
        )
        lane.append(
            lambda c: {
                (1, c): f"SRA R1, R1, {S}",
                (2, c): "LWI R1, ROUT",
            }
        )
        lane.append(lambda c: {(1, c): "SADD R1, R1, RCB"})
    lane.append(lambda c: {(1, c): "SWD R1"})

    # Stagger starts by column index
    starts = [0, 1, 2, 3]
    total_len = max(starts[c] + len(lane) for c in range(4)) + 1  # +1 for EXIT
    ops_by_t = [dict() for _ in range(total_len)]

    for c in range(4):
        for i, emit in enumerate(lane):
            t = starts[c] + i
            ops_by_t[t].update(emit(c))

    # Put EXIT at the very end
    ops_by_t[-1][(3, 3)] = "EXIT"

    I = [G(ops) for ops in ops_by_t]

    mem = []
    for c in range(4):
        mem.append((c * 8, xvals[c]))
        mem.append((c * 8 + 4, xmi))
    for i, cs in enumerate(segs):
        for k, cv in enumerate(cs):
            mem.append((LUT_BASE + i * stride + k * 4, cv))

    a, e, err = hcheck(x_test, O, S, segs, xmi)
    chk("STAGGERED_QUAD", O, S, a, e, err)

    return write(
        "STAGGERED_QUAD",
        O,
        S,
        I,
        mem,
        segs,
        {
            "axis": "throughput",
            "throughput_factor": 4,
            "launch_stagger": starts,
            "load_addrs": [0, 8, 16, 24],
            "store_addrs": [10000, 10004, 10008, 10012],
        },
    )


# ══════════════════════════════════════════════════════════════════
#  AXIS 4: ALGORITHM / COEFFICIENT MODEL
# ══════════════════════════════════════════════════════════════════


def fit_deriv1_segs(S, xmin=X_MIN, xmax=X_MAX):
    """Store [a0, a1] with a0=sin(x0), a1=h*cos(x0), polynomial in t=dx/2^S."""
    xmi, xma, w = round(xmin * SCALE), round(xmax * SCALE), 1 << S
    n = (xma - xmi) >> S
    h = w / SCALE
    segs = []
    for i in range(n):
        x0 = xmin + i * h
        a0 = round(math.sin(x0) * SCALE)
        a1 = round(h * math.cos(x0) * SCALE)
        segs.append([a0, a1])
    return segs, n


def fit_deriv3_anchor_segs(S, xmin=X_MIN, xmax=X_MAX):
    """Store only [sin(x0), cos(x0)] anchors; cubic is reconstructed with constants."""
    xmi, xma, w = round(xmin * SCALE), round(xmax * SCALE), 1 << S
    n = (xma - xmi) >> S
    h = w / SCALE
    segs = []
    for i in range(n):
        x0 = xmin + i * h
        s0 = round(math.sin(x0) * SCALE)
        c0 = round(math.cos(x0) * SCALE)
        segs.append([s0, c0])
    return segs, n


def deriv3_consts(S):
    w = 1 << S
    h = w / SCALE
    return (
        round(h * (1 << S)),
        round((0.5 * h * h) * (1 << S)),
        round((h * h * h / 6.0) * (1 << S)),
    )


def hcheck_deriv1(xt, S, segs, xmi):
    w, m = 1 << S, (1 << S) - 1
    xi = round(xt * SCALE)
    dt = xi - xmi
    idx = dt >> S
    dx = dt & m
    if idx < 0 or idx >= len(segs):
        return None, None, None
    a0, a1 = segs[idx]
    acc = ((a1 * dx) >> S) + a0
    exp = round(func(xt) * SCALE)
    return acc, exp, abs(acc - exp) / SCALE


def hcheck_deriv3(xt, S, segs, xmi):
    w, m = 1 << S, (1 << S) - 1
    xi = round(xt * SCALE)
    dt = xi - xmi
    idx = dt >> S
    dx = dt & m
    if idx < 0 or idx >= len(segs):
        return None, None, None
    s0, c0 = segs[idx]
    k1, k2, k3 = deriv3_consts(S)
    a1 = (c0 * k1) >> S
    a2 = -((s0 * k2) >> S)
    a3 = -((c0 * k3) >> S)
    acc = a3
    acc = ((acc * dx) >> S) + a2
    acc = ((acc * dx) >> S) + a1
    acc = ((acc * dx) >> S) + s0
    exp = round(func(xt) * SCALE)
    return acc, exp, abs(acc - exp) / SCALE


def qwave_reduce_fp(xi):
    pi = round(math.pi * SCALE)
    hpi = round(math.pi / 2 * SCALE)
    sign = 1
    if xi >= pi:
        xi -= pi
        sign = -1
    if xi >= hpi:
        xi = pi - xi
    return xi, sign


def hcheck_deriv3_qwave(xt, S, segs):
    w, m = 1 << S, (1 << S) - 1
    xi = round(xt * SCALE)
    xr, sign = qwave_reduce_fp(xi)
    idx = xr >> S
    dx = xr & m
    if idx < 0 or idx >= len(segs):
        idx = min(max(idx, 0), len(segs) - 1)
    s0, c0 = segs[idx]
    k1, k2, k3 = deriv3_consts(S)
    a1 = (c0 * k1) >> S
    a2 = -((s0 * k2) >> S)
    a3 = -((c0 * k3) >> S)
    acc = a3
    acc = ((acc * dx) >> S) + a2
    acc = ((acc * dx) >> S) + a1
    acc = ((acc * dx) >> S) + s0
    acc *= sign
    exp = round(func(xt) * SCALE)
    return acc, exp, abs(acc - exp) / SCALE


def gen_DERIV1(O, S, x_test):
    """Anchor-slope LUT: store [sin(x0), h*cos(x0)] and evaluate one local linear step."""
    xmi, _, w, mask, _, _, _ = derived(O, S)
    stride = 8
    segs, _ = fit_deriv1_segs(S)
    xt = round(x_test * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0"}))
    I.append(G({(0, 0): "LWD R1"}))
    I.append(G({(0, 0): "SSUB R0, R0, R1"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}"}))
    I.append(G({(0, 0): f"SMUL R1, R1, {stride}"}))
    I.append(G({(0, 0): f"SADD R1, R1, {LUT_BASE}"}))
    I.append(G({(0, 0): "LWI R2, R1"}))
    I.append(G({(0, 0): f"SADD R3, R1, 4"}))
    I.append(G({(0, 0): "LWI R3, R3"}))
    I.append(G({(0, 0): "SMUL R3, R3, R0"}))
    I.append(G({(0, 0): f"SRA R3, R3, {S}"}))
    I.append(G({(0, 0): "SADD R2, R2, R3"}))
    I.append(G({(0, 0): "SWD R2", (0, 3): "EXIT"}))
    a, e, err = hcheck_deriv1(x_test, S, segs, xmi)
    chk("DERIV1", O, S, a, e, err)
    return write(
        "DERIV1",
        O,
        S,
        I,
        mem_lut(segs, stride, [(0, xt), (4, xmi)]),
        segs,
        {
            "axis": "algorithm",
            "load_addrs": [0, 0, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
            "lut_words_override": len(segs) * 2,
            "n_segments_override": len(segs),
        },
    )


def gen_DERIV3(O, S, x_test):
    """Anchor LUT: store [sin(x0), cos(x0)], reconstruct cubic Taylor locally."""
    xmi, _, w, mask, _, _, _ = derived(O, S)
    stride = 8
    segs, _ = fit_deriv3_anchor_segs(S)
    xt = round(x_test * SCALE)
    k1, k2, k3 = deriv3_consts(S)
    I = []
    I.append(G({(0, 0): "LWD R0"}))
    I.append(G({(0, 0): "LWD R1"}))
    I.append(G({(0, 0): "SSUB R0, R0, R1"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}"}))
    I.append(G({(0, 0): f"SMUL R1, R1, {stride}"}))
    I.append(G({(0, 0): f"SADD R1, R1, {LUT_BASE}"}))
    I.append(G({(0, 0): "LWI R2, R1"}))
    I.append(G({(0, 0): f"SADD R3, R1, 4"}))
    I.append(G({(0, 0): "LWI R3, R3"}))
    I.append(G({(0, 0): f"SMUL R3, R3, {k3}"}))
    I.append(G({(0, 0): f"SRA R3, R3, {S}"}))
    I.append(G({(0, 0): "SSUB R3, ZERO, R3"}))
    I.append(G({(0, 0): "SMUL R3, R3, R0"}))
    I.append(G({(0, 0): f"SRA R3, R3, {S}"}))
    I.append(G({(0, 0): f"SMUL R2, R2, {k2}"}))
    I.append(G({(0, 0): f"SRA R2, R2, {S}"}))
    I.append(G({(0, 0): "SSUB R2, ZERO, R2"}))
    I.append(G({(0, 0): "SADD R3, R3, R2"}))
    I.append(G({(0, 0): "SMUL R3, R3, R0"}))
    I.append(G({(0, 0): f"SRA R3, R3, {S}"}))
    I.append(G({(0, 0): f"SADD R2, R1, 4"}))
    I.append(G({(0, 0): "LWI R2, R2"}))
    I.append(G({(0, 0): f"SMUL R2, R2, {k1}"}))
    I.append(G({(0, 0): f"SRA R2, R2, {S}"}))
    I.append(G({(0, 0): "SADD R3, R3, R2"}))
    I.append(G({(0, 0): "SMUL R3, R3, R0"}))
    I.append(G({(0, 0): f"SRA R3, R3, {S}"}))
    I.append(G({(0, 0): "LWI R2, R1"}))
    I.append(G({(0, 0): "SADD R3, R3, R2"}))
    I.append(G({(0, 0): "SWD R3", (0, 3): "EXIT"}))
    a, e, err = hcheck_deriv3(x_test, S, segs, xmi)
    chk("DERIV3", O, S, a, e, err)
    return write(
        "DERIV3",
        O,
        S,
        I,
        mem_lut(segs, stride, [(0, xt), (4, xmi)]),
        segs,
        {
            "axis": "algorithm",
            "load_addrs": [0, 0, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
            "lut_words_override": len(segs) * 2,
            "n_segments_override": len(segs),
        },
    )


def gen_DERIV3_QWAVE(O, S, x_test):
    """Quarter-wave anchor LUT: [sin(x0), cos(x0)] over [0, pi/2], cubic local Taylor."""
    hpi = round(math.pi / 2 * SCALE)
    pi = round(math.pi * SCALE)
    _, _, w, mask, _, _, _ = derived(O, S, 0.0, math.pi / 2)
    stride = 8
    segs, _ = fit_deriv3_anchor_segs(S, 0.0, math.pi / 2)
    xt = round(x_test * SCALE)
    k1, k2, k3 = deriv3_consts(S)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 1): "LWD R1"}))
    I.append(G({(0, 1): "LWD R2"}))
    I.append(G({(1, 0): "SADD R3, ZERO, 1"}))
    I.append(G({(0, 0): "SSUB R1, R0, RCR"}))
    I.append(G({(0, 0): "BSFA R0, R0, R1, SELF", (1, 0): "BSFA R3, R3, ZERO, RCT"}))
    I.append(G({(1, 0): "SADD R3, R3, R3"}))
    I.append(G({(1, 0): "SSUB R3, R3, 1"}))
    I.append(G({(0, 1): "SADD ROUT, R1, 0"}))
    I.append(G({(0, 0): "SSUB R1, R0, RCR"}))
    I.append(G({(0, 0): "SSUB R2, RCR, R1"}))
    I.append(G({(0, 0): "BSFA R0, R0, R2, SELF"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}"}))
    I.append(G({(0, 0): f"SMUL R1, R1, {stride}"}))
    I.append(G({(0, 0): f"SADD R1, R1, {LUT_BASE}"}))
    I.append(G({(0, 0): "LWI R2, R1"}))
    I.append(G({(0, 0): f"SADD R3, R1, 4"}))
    I.append(G({(0, 0): "LWI R3, R3"}))
    I.append(G({(0, 0): f"SMUL R3, R3, {k3}"}))
    I.append(G({(0, 0): f"SRA R3, R3, {S}"}))
    I.append(G({(0, 0): "SSUB R3, ZERO, R3"}))
    I.append(G({(0, 0): "SMUL R3, R3, R0"}))
    I.append(G({(0, 0): f"SRA R3, R3, {S}"}))
    I.append(G({(0, 0): f"SMUL R2, R2, {k2}"}))
    I.append(G({(0, 0): f"SRA R2, R2, {S}"}))
    I.append(G({(0, 0): "SSUB R2, ZERO, R2"}))
    I.append(G({(0, 0): "SADD R3, R3, R2"}))
    I.append(G({(0, 0): "SMUL R3, R3, R0"}))
    I.append(G({(0, 0): f"SRA R3, R3, {S}"}))
    I.append(G({(0, 0): f"SADD R2, R1, 4"}))
    I.append(G({(0, 0): "LWI R2, R2"}))
    I.append(G({(0, 0): f"SMUL R2, R2, {k1}"}))
    I.append(G({(0, 0): f"SRA R2, R2, {S}"}))
    I.append(G({(0, 0): "SADD R3, R3, R2"}))
    I.append(G({(0, 0): "SMUL R3, R3, R0"}))
    I.append(G({(0, 0): f"SRA R3, R3, {S}"}))
    I.append(G({(0, 0): "LWI R2, R1"}))
    I.append(G({(0, 0): "SADD R2, R3, R2"}))
    I.append(G({(0, 0): "SMUL R2, R2, R3"}))
    I.append(G({(0, 0): "SWD R2", (0, 3): "EXIT"}))
    mem = [(0, xt), (4, 0), (8, hpi), (12, pi)]
    for i, cs in enumerate(segs):
        for k, c in enumerate(cs):
            mem.append((LUT_BASE + i * stride + k * 4, c))
    a, e, err = hcheck_deriv3_qwave(x_test, S, segs)
    chk("DERIV3_QWAVE", O, S, a, e, err)
    return write(
        "DERIV3_QWAVE",
        O,
        S,
        I,
        mem,
        segs,
        {
            "axis": "algorithm",
            "load_addrs": [0, 4, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
            "lut_words_override": len(segs) * 2,
            "n_segments_override": len(segs),
        },
    )


# ── Runner ─────────────────────────────────────────────────────────
ALL = [
    gen_SEQ,
    gen_PIPE2,
    gen_PIPE3,
    gen_HYBRID,
    gen_LOOP,
    gen_WIDE,
    gen_DENSE,
    gen_HWAVE,
    gen_QWAVE,
    gen_DUAL,
    gen_QUAD,
    gen_STAGGERED_QUAD,
    gen_DERIV1,
    gen_DERIV3,
    gen_DERIV3_QWAVE,
]


def run_sweep(ORDER=None, shifts=None, x_test=None):
    # def run_sweep(shifts=None):
    if shifts is None:
        shifts = [8, 9, 10, 11, 12]
    if ORDER is None:
        ORDER = [1, 2, 3, 4, 5]
    elif isinstance(ORDER, int):
        ORDER = [ORDER]
    elif isinstance(ORDER, tuple):
        ORDER = list(ORDER)
    # empty list [] is valid; loop will simply do nothing
    os.makedirs("pareto_out", exist_ok=True)
    all_m = []
    for O in ORDER:
        for S in shifts:
            print(f"\n── SHIFT={S} ──")
            for g in ALL:
                try:
                    all_m.append(g(O, S, x_test))
                except Exception as e:
                    print(f"  FAIL {g.__name__}: {e}")
        if all_m:
            keys = list(dict.fromkeys(k for m in all_m for k in m.keys()))
            for m in all_m:
                for k in keys:
                    m.setdefault(k, "")
            with open("pareto_out/summary.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys)
                w.writeheader()
                w.writerows(all_m)
        print(f"\n{'='*50}\n  {len(all_m)} variants generated\n{'='*50}")
    return all_m


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--x_test", type=float, default=1.0)
    p.add_argument("--order", type=int, nargs="*", default=[1, 2, 3, 4, 5])
    p.add_argument("--shifts", type=int, nargs="+", default=[8, 9, 10, 11, 12])
    a = p.parse_args()
    # run_sweep(a.order, a.shifts)
    run_sweep(a.order, a.shifts, a.x_test)
