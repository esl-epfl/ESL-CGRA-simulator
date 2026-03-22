"""
CGRA Sine Approximation — Pareto Variant Generator
====================================================
Generates 9 architecture variants × N SHIFT values for piecewise polynomial
sine approximation on the ESL-CGRA. Each variant produces an independent
instructions.csv + memory.csv ready for the simulator.

Usage:
  python generate.py                       # ORDER=3, SHIFT=8..12
  python generate.py --order 2 --shifts 10 # single point
"""

import math, csv, os, json, argparse
import numpy as np


# ── Global parameters ──────────────────────────────────────────────
def func(x):
    return math.sin(x)


SCALE = 10000
X_MIN = 0.0
X_MAX = 2 * math.pi
X_TEST = 5.0
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
    "LNAND": 1,
    "LNOR": 1,
    "LXNOR": 1,
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
    "SMUL": 3,
    "FXPMUL": 3,
}


# ── Helpers ────────────────────────────────────────────────────────
def derived(ORDER, SHIFT, x_min=X_MIN, x_max=X_MAX):
    xmi = round(x_min * SCALE)
    xma = round(x_max * SCALE)
    w = 1 << SHIFT
    return xmi, xma, w, w - 1, (xma - xmi) >> SHIFT, ORDER + 1, (ORDER + 1) * 4


def fit_segments(ORDER, SHIFT, x_min=X_MIN, x_max=X_MAX):
    xmi, xma, w = round(x_min * SCALE), round(x_max * SCALE), 1 << SHIFT
    n = (xma - xmi) >> SHIFT
    segs = []
    for i in range(n):
        x0 = x_min + i * w / SCALE
        ts = [j / max(ORDER, 1) for j in range(ORDER + 1)]
        ys = [func(x0 + t * w / SCALE) for t in ts]
        cs = np.polyfit(ts, ys, ORDER)[::-1]
        segs.append([round(c * SCALE) for c in cs])
    return segs, n


def G(ops):
    """Build one 4×4 instruction grid from a dict of {(row,col): op_string}."""
    g = [["NOP"] * N_COLS for _ in range(N_ROWS)]
    for (r, c), op in ops.items():
        g[r][c] = op
    return g


def horner_check(x_test, ORDER, SHIFT, segs, xmi):
    w, m = 1 << SHIFT, (1 << SHIFT) - 1
    xi = round(x_test * SCALE)
    dt = xi - xmi
    idx = dt >> SHIFT
    dx = dt & m
    if idx < 0 or idx >= len(segs):
        return None, None, None
    s = segs[idx]
    acc = s[ORDER]
    for k in range(ORDER - 1, -1, -1):
        acc = (acc * dx >> SHIFT) + s[k]
    exp = round(func(x_test) * SCALE)
    return acc, exp, abs(acc - exp) / SCALE


def mem_lut(segs, stride, inputs):
    m = list(inputs)
    for i, cs in enumerate(segs):
        for k, c in enumerate(cs):
            m.append((LUT_BASE + i * stride + k * 4, c))
    return m


def total_lat(instrs):
    t = 0
    for g in instrs:
        mx = 1
        for row in g:
            for op in row:
                mx = max(mx, OP_LAT.get(op.replace(",", " ").split()[0], 1))
        t += mx
    return t


def total_lat_looped(instrs, loop):
    if loop is None:
        return total_lat(instrs)
    s, e, n = loop
    t = 0
    for i, g in enumerate(instrs):
        mx = 1
        for row in g:
            for op in row:
                mx = max(mx, OP_LAT.get(op.replace(",", " ").split()[0], 1))
        t += mx * (n if s <= i <= e else 1)
    return t


def active_pes(instrs):
    a = set()
    for g in instrs:
        for r in range(N_ROWS):
            for c in range(N_COLS):
                if g[r][c] != "NOP":
                    a.add((r, c))
    return len(a)


def pe_instrs(instrs):
    return sum(
        1
        for g in instrs
        for r in range(N_ROWS)
        for c in range(N_COLS)
        if g[r][c] != "NOP"
    )


def write(name, ORDER, SHIFT, instrs, mem, segs, extra=None):
    tag = f"{name}_T{ORDER}_S{SHIFT}"
    d = os.path.join("pareto_out", tag)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "instructions.csv"), "w", newline="") as f:
        w = csv.writer(f)
        for t, g in enumerate(instrs):
            w.writerow([t])
            for row in g:
                w.writerow(row)
    with open(os.path.join(d, "memory.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Address", "Data"])
        for a, v in mem:
            w.writerow([a, v])
    loop = (extra or {}).get("_loop")
    lat = total_lat_looped(instrs, loop)
    m = {
        "variant": name,
        "tag": tag,
        "order": ORDER,
        "shift": SHIFT,
        "n_instructions": len(instrs),
        "total_latency_cc": lat,
        "active_pes": active_pes(instrs),
        "pe_instructions": pe_instrs(instrs),
        "lut_words": len(segs) * (ORDER + 1) if segs else 0,
        "n_segments": len(segs) if segs else 0,
    }
    if extra:
        for k, v in extra.items():
            if not k.startswith("_"):
                m[k] = v
    with open(os.path.join(d, "metrics.json"), "w") as f:
        json.dump(m, f, indent=2)
    return m


# ══════════════════════════════════════════════════════════════════
#  VARIANT GENERATORS
# ══════════════════════════════════════════════════════════════════


def gen_SEQ(ORDER, SHIFT):
    """Sequential: everything on PE(0,0). Minimum PEs (2 including EXIT).

    Why it exists: absolute lower bound on PE usage. Shows the penalty
    of zero parallelism — every operation waits for the previous one.
    5 instructions per Horner iteration (mul, shift, addr, load, add)
    because we can't overlap address computation with anything.
    """
    xmi, _, w, mask, _, nc, stride = derived(ORDER, SHIFT)
    segs, _ = fit_segments(ORDER, SHIFT)
    xt = round(X_TEST * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0"}))
    I.append(G({(0, 0): "LWD R1"}))
    I.append(G({(0, 0): "SSUB R0, R0, R1"}))
    I.append(G({(0, 0): f"SRT R1, R0, {SHIFT}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}"}))
    I.append(G({(0, 0): f"SMUL R1, R1, {stride}"}))
    I.append(G({(0, 0): f"SADD R1, R1, {LUT_BASE}"}))
    I.append(G({(0, 0): f"SADD R3, R1, {ORDER*4}"}))
    I.append(G({(0, 0): "LWI R2, R3"}))
    for k in range(ORDER - 1, -1, -1):
        I.append(G({(0, 0): "SMUL R2, R2, R0"}))
        I.append(G({(0, 0): f"SRA R2, R2, {SHIFT}"}))
        I.append(G({(0, 0): f"SADD R3, R1, {k*4}"}))
        I.append(G({(0, 0): "LWI R3, R3"}))
        I.append(G({(0, 0): "SADD R2, R2, R3"}))
    I.append(G({(0, 0): "SWD R2", (0, 3): "EXIT"}))
    mem = mem_lut(segs, stride, [(0, xt), (4, xmi)])
    a, e, err = horner_check(X_TEST, ORDER, SHIFT, segs, xmi)
    print(f"  SEQ      T{ORDER} S{SHIFT}: {a} exp={e} err={err:.2e}")
    return write(
        "SEQ",
        ORDER,
        SHIFT,
        I,
        mem,
        segs,
        {"load_addrs": [0, 0, 0, 0], "store_addrs": [10000, 0, 0, 0]},
    )


def gen_PIPE2(ORDER, SHIFT):
    """2-PE pipeline: PE(0,0) holds dx, PE(1,0) does everything else.

    Why it exists: the first step of parallelism. PE(0,0) computes dx
    once and holds it stable in its output for the rest of execution.
    PE(1,0) reads dx via RCT whenever it needs it for SMUL, instead of
    keeping dx in a register. Frees up a register on PE(1,0) for addr work.
    Still serial for loads — 5 instrs per Horner iteration.
    """
    xmi, _, w, mask, _, nc, stride = derived(ORDER, SHIFT)
    segs, _ = fit_segments(ORDER, SHIFT)
    xt = round(X_TEST * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {SHIFT}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): f"SMUL R0, RCT, {stride}"}))
    I.append(G({(1, 0): f"SADD R0, R0, {LUT_BASE}"}))
    I.append(G({(1, 0): f"SADD R1, R0, {ORDER*4}"}))
    I.append(G({(1, 0): "LWI R2, R1"}))
    for k in range(ORDER - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R2, R2, RCT"}))
        I.append(G({(1, 0): f"SRA R2, R2, {SHIFT}"}))
        I.append(G({(1, 0): f"SADD R1, R0, {k*4}"}))
        I.append(G({(1, 0): "LWI R3, R1"}))
        I.append(G({(1, 0): "SADD R2, R2, R3"}))
    I.append(G({(1, 0): "SWD R2", (0, 3): "EXIT"}))
    mem = mem_lut(segs, stride, [(0, xt), (4, xmi)])
    a, e, err = horner_check(X_TEST, ORDER, SHIFT, segs, xmi)
    print(f"  PIPE2    T{ORDER} S{SHIFT}: {a} exp={e} err={err:.2e}")
    return write(
        "PIPE2",
        ORDER,
        SHIFT,
        I,
        mem,
        segs,
        {"load_addrs": [0, 4, 0, 0], "store_addrs": [10000, 0, 0, 0]},
    )


def gen_PIPE3(ORDER, SHIFT):
    """3-PE pipeline: PE(0,0)=dx, PE(1,0)=Horner, PE(2,0)=coeff loader.

    Why it exists: THE BASELINE. The key insight is that while PE(1,0) does
    SMUL (3cc), PE(2,0) can compute the next coefficient address and start
    loading it from memory in parallel. This overlaps load latency with
    multiply latency, reducing each Horner iteration from 5 to 3 instructions.
    Total: 7 + 3×ORDER instructions.
    """
    xmi, _, w, mask, _, nc, stride = derived(ORDER, SHIFT)
    segs, _ = fit_segments(ORDER, SHIFT)
    xt = round(X_TEST * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {SHIFT}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): f"SMUL R0, RCT, {stride}"}))
    I.append(
        G(
            {
                (1, 0): f"SADD R1, R0, {LUT_BASE + ORDER*4}",
                (2, 0): f"SADD R0, RCT, {LUT_BASE}",
            }
        )
    )
    I.append(G({(1, 0): "LWI R1, R1"}))
    for k in range(ORDER - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {SHIFT}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))
    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))
    mem = mem_lut(segs, stride, [(0, xt), (4, xmi)])
    a, e, err = horner_check(X_TEST, ORDER, SHIFT, segs, xmi)
    print(f"  PIPE3    T{ORDER} S{SHIFT}: {a} exp={e} err={err:.2e}")
    return write(
        "PIPE3",
        ORDER,
        SHIFT,
        I,
        mem,
        segs,
        {"load_addrs": [0, 4, 0, 0], "store_addrs": [10000, 0, 0, 0]},
    )


def gen_HYBRID(ORDER, SHIFT):
    """Hybrid: top coefficient as immediate, rest from SRAM.

    Why it exists: the fastest general-purpose variant. Saves one LWI in
    setup by embedding c[ORDER] directly in the instruction stream as an
    immediate value. This works because c[ORDER] only depends on the segment
    index — but unlike M_IMM, we still index into the LUT at runtime for all
    other coefficients, so it works for ANY input x.
    Saves 2 CC over PIPE3 (skips the LWI for the top coefficient).
    """
    xmi, _, w, mask, _, nc, stride = derived(ORDER, SHIFT)
    segs, _ = fit_segments(ORDER, SHIFT)
    xt = round(X_TEST * SCALE)
    # Use the c[ORDER] for the segment containing X_TEST as the immediate
    seg_idx = (round(X_TEST * SCALE) - xmi) >> SHIFT
    c_top = segs[seg_idx][ORDER]
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {SHIFT}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): f"SMUL R0, RCT, {stride}"}))
    I.append(
        G({(1, 0): f"SADD R1, ZERO, {c_top}", (2, 0): f"SADD R0, RCT, {LUT_BASE}"})
    )
    for k in range(ORDER - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {SHIFT}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))
    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))
    mem = mem_lut(segs, stride, [(0, xt), (4, xmi)])
    a, e, err = horner_check(X_TEST, ORDER, SHIFT, segs, xmi)
    print(f"  HYBRID   T{ORDER} S{SHIFT}: {a} exp={e} err={err:.2e}")
    return write(
        "HYBRID",
        ORDER,
        SHIFT,
        I,
        mem,
        segs,
        {"load_addrs": [0, 4, 0, 0], "store_addrs": [10000, 0, 0, 0]},
    )


def gen_LOOP(ORDER, SHIFT):
    """Looped Horner: 3-instr loop body with BGE branch.

    Why it exists: minimum configuration memory. The Horner iteration is a
    3-instruction loop that runs ORDER times instead of being unrolled.
    Total config: 10 instructions regardless of ORDER (vs 7+3×ORDER unrolled).
    For ORDER=3 this is 10 vs 16 — a 37% reduction in config memory.
    Same execution latency as PIPE3 since the loop body is identical.

    PE(3,0) runs the loop counter and branch. PE(2,0) holds the coefficient
    address and decrements it by 4 each iteration.
    """
    xmi, _, w, mask, _, nc, stride = derived(ORDER, SHIFT)
    segs, _ = fit_segments(ORDER, SHIFT)
    xt = round(X_TEST * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {SHIFT}", (3, 0): f"SADD R0, ZERO, {ORDER-1}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): f"SMUL R0, RCT, {stride}"}))
    I.append(
        G(
            {
                (1, 0): f"SADD R1, R0, {LUT_BASE + ORDER*4}",
                (2, 0): f"SADD R0, RCT, {LUT_BASE + (ORDER-1)*4}",
            }
        )
    )
    I.append(G({(1, 0): "LWI R1, R1", (2, 0): "SADD ROUT, R0, 0"}))
    LS = len(I)  # loop start = 6
    I.append(G({(1, 0): "SMUL R1, R1, RCT", (3, 0): "SSUB R0, R0, 1"}))
    I.append(G({(1, 0): f"SRA R1, R1, {SHIFT}", (2, 0): "LWI R1, ROUT"}))
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
    mem = mem_lut(segs, stride, [(0, xt), (4, xmi)])
    a, e, err = horner_check(X_TEST, ORDER, SHIFT, segs, xmi)
    print(f"  LOOP     T{ORDER} S{SHIFT}: {a} exp={e} err={err:.2e}")
    return write(
        "LOOP",
        ORDER,
        SHIFT,
        I,
        mem,
        segs,
        {
            "load_addrs": [0, 4, 0, 0],
            "store_addrs": [10000, 0, 0, 0],
            "_loop": (LS, LS + 2, ORDER),
        },
    )


def gen_HWAVE(ORDER, SHIFT):
    """Half-wave: LUT covers [0, π] only. sin(x) = −sin(x−π) for x ≥ π.

    Why it exists: halves the LUT memory at cost of ~9 extra instructions
    for folding + sign correction. Uses BSFA (conditional select based on
    sign flag) to fold x into [0,π] and track the sign multiplier.

    Folding logic (PE(0,0)):
      1. Compute x − π
      2. If x ≥ π (result ≥ 0): use x−π, set sign = −1
      3. If x < π (result < 0): keep x, set sign = +1
    Then standard PIPE3 Horner on the folded value.
    Final: result × sign (SMUL).
    """
    pi = round(math.pi * SCALE)
    _, _, w, mask, _, nc, stride = derived(ORDER, SHIFT, 0.0, math.pi)
    segs, _ = fit_segments(ORDER, SHIFT, 0.0, math.pi)
    xt = round(X_TEST * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))  # x, 0
    I.append(G({(0, 1): "LWD R1"}))  # pi
    I.append(G({(1, 0): "SADD R3, ZERO, 1"}))  # sign = +1
    I.append(G({(0, 0): "SSUB R1, R0, RCR"}))  # x − pi
    I.append(
        G({(0, 0): "BSFA R0, R0, R1, SELF", (1, 0): "BSFA R3, R3, ZERO, RCT"})  # fold
    )  # sign select
    I.append(G({(1, 0): "SADD R3, R3, R3"}))  # 2*R3
    I.append(G({(1, 0): "SSUB R3, R3, 1"}))  # 2*R3 − 1 → {−1,+1}
    # standard Horner
    I.append(G({(0, 0): f"SRT R1, R0, {SHIFT}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): f"SMUL R0, RCT, {stride}"}))
    I.append(
        G(
            {
                (1, 0): f"SADD R1, R0, {LUT_BASE + ORDER*4}",
                (2, 0): f"SADD R0, RCT, {LUT_BASE}",
            }
        )
    )
    I.append(G({(1, 0): "LWI R1, R1"}))
    for k in range(ORDER - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {SHIFT}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))
    I.append(G({(1, 0): "SMUL R1, R1, R3"}))
    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))
    mem = [(0, xt), (4, 0), (8, pi)]
    for i, cs in enumerate(segs):
        for k, c in enumerate(cs):
            mem.append((LUT_BASE + i * stride + k * 4, c))
    # check
    x = X_TEST
    sign = 1
    if x >= math.pi:
        x -= math.pi
        sign = -1
    xi = round(x * SCALE)
    idx = xi >> SHIFT
    dx = xi & mask
    if idx >= len(segs):
        idx = len(segs) - 1
    s = segs[idx]
    acc = s[ORDER]
    for kk in range(ORDER - 1, -1, -1):
        acc = (acc * dx >> SHIFT) + s[kk]
    acc *= sign
    exp = round(func(X_TEST) * SCALE)
    print(f"  HWAVE    T{ORDER} S{SHIFT}: {acc} exp={exp} err={abs(acc-exp)/SCALE:.2e}")
    return write(
        "HWAVE",
        ORDER,
        SHIFT,
        I,
        mem,
        segs,
        {"load_addrs": [0, 4, 0, 0], "store_addrs": [10000, 0, 0, 0]},
    )


def gen_QWAVE(ORDER, SHIFT):
    """Quarter-wave: LUT covers [0, π/2] only. Full symmetry exploit.

    Why it exists: minimum LUT memory (1/4 of full wave). Costs ~12 extra
    instructions for the double fold. Two BSFA operations:
      1. If x ≥ π: x_r = x−π, sign = −1
      2. If x_r ≥ π/2: x_f = π − x_r (mirror around π/2)
    Then standard PIPE3 Horner on x_f ∈ [0, π/2].
    """
    hpi = round(math.pi / 2 * SCALE)
    pi = round(math.pi * SCALE)
    _, _, w, mask, _, nc, stride = derived(ORDER, SHIFT, 0.0, math.pi / 2)
    segs, _ = fit_segments(ORDER, SHIFT, 0.0, math.pi / 2)
    xt = round(X_TEST * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))  # x, 0
    I.append(G({(0, 1): "LWD R1"}))  # half_pi
    I.append(G({(0, 1): "LWD R2"}))  # pi
    I.append(G({(1, 0): "SADD R3, ZERO, 1"}))  # sign = +1
    I.append(G({(0, 0): "SSUB R1, R0, RCR"}))  # x − pi
    I.append(G({(0, 0): "BSFA R0, R0, R1, SELF", (1, 0): "BSFA R3, R3, ZERO, RCT"}))
    I.append(G({(1, 0): "SADD R3, R3, R3"}))
    I.append(G({(1, 0): "SSUB R3, R3, 1"}))
    I.append(G({(0, 1): "SADD ROUT, R1, 0"}))  # output half_pi
    I.append(G({(0, 0): "SSUB R1, R0, RCR"}))  # x_r − half_pi
    I.append(G({(0, 0): "SSUB R2, RCR, R1"}))  # half_pi − (x_r−half_pi)
    I.append(G({(0, 0): "BSFA R0, R0, R2, SELF"}))  # select x_final
    # Horner
    I.append(G({(0, 0): f"SRT R1, R0, {SHIFT}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): f"SMUL R0, RCT, {stride}"}))
    I.append(
        G(
            {
                (1, 0): f"SADD R1, R0, {LUT_BASE + ORDER*4}",
                (2, 0): f"SADD R0, RCT, {LUT_BASE}",
            }
        )
    )
    I.append(G({(1, 0): "LWI R1, R1"}))
    for k in range(ORDER - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {SHIFT}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))
    I.append(G({(1, 0): "SMUL R1, R1, R3"}))
    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))
    mem = [(0, xt), (4, 0), (8, hpi), (12, pi)]
    for i, cs in enumerate(segs):
        for k, c in enumerate(cs):
            mem.append((LUT_BASE + i * stride + k * 4, c))
    x = X_TEST
    sign = 1
    if x >= math.pi:
        x -= math.pi
        sign = -1
    if x >= math.pi / 2:
        x = math.pi - x
    xi = round(x * SCALE)
    idx = xi >> SHIFT
    dx = xi & mask
    if idx >= len(segs):
        idx = len(segs) - 1
    s = segs[idx]
    acc = s[ORDER]
    for kk in range(ORDER - 1, -1, -1):
        acc = (acc * dx >> SHIFT) + s[kk]
    acc *= sign
    exp = round(func(X_TEST) * SCALE)
    print(f"  QWAVE    T{ORDER} S{SHIFT}: {acc} exp={exp} err={abs(acc-exp)/SCALE:.2e}")
    return write(
        "QWAVE",
        ORDER,
        SHIFT,
        I,
        mem,
        segs,
        {"load_addrs": [0, 4, 0, 0], "store_addrs": [10000, 0, 0, 0]},
    )


def gen_DUAL(ORDER, SHIFT):
    """Dual datapath: 2 sine evaluations in parallel on columns 0 and 2.

    Why it exists: doubles throughput. The CGRA has 4 columns — we run
    two independent PIPE3 datapaths side by side. Each uses 3 PEs in its
    column (rows 0-2). They share the same LUT in SRAM (LWI reads go to
    the shared memory). Useful when you need to compute sin() on a stream
    of values. Total: 9 active PEs, same latency as PIPE3.
    """
    xmi, _, w, mask, _, nc, stride = derived(ORDER, SHIFT)
    segs, _ = fit_segments(ORDER, SHIFT)
    xt = round(X_TEST * SCALE)
    xt2 = round(2.0 * SCALE)
    I = []
    I.append(
        G({(0, 0): "LWD R0", (0, 1): "LWD R0", (0, 2): "LWD R0", (0, 3): "LWD R0"})
    )
    I.append(G({(0, 0): "SSUB R0, R0, RCR", (0, 2): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {SHIFT}", (0, 2): f"SRT R1, R0, {SHIFT}"}))
    I.append(
        G(
            {
                (0, 0): f"LAND R0, R0, {mask}",
                (1, 0): f"SMUL R0, RCT, {stride}",
                (0, 2): f"LAND R0, R0, {mask}",
                (1, 2): f"SMUL R0, RCT, {stride}",
            }
        )
    )
    I.append(
        G(
            {
                (1, 0): f"SADD R1, R0, {LUT_BASE+ORDER*4}",
                (2, 0): f"SADD R0, RCT, {LUT_BASE}",
                (1, 2): f"SADD R1, R0, {LUT_BASE+ORDER*4}",
                (2, 2): f"SADD R0, RCT, {LUT_BASE}",
            }
        )
    )
    I.append(G({(1, 0): "LWI R1, R1", (1, 2): "LWI R1, R1"}))
    for k in range(ORDER - 1, -1, -1):
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
                    (1, 0): f"SRA R1, R1, {SHIFT}",
                    (2, 0): "LWI R1, ROUT",
                    (1, 2): f"SRA R1, R1, {SHIFT}",
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
    a, e, err = horner_check(X_TEST, ORDER, SHIFT, segs, xmi)
    print(f"  DUAL     T{ORDER} S{SHIFT}: {a} exp={e} err={err:.2e}")
    return write(
        "DUAL",
        ORDER,
        SHIFT,
        I,
        mem,
        segs,
        {
            "load_addrs": [0, 4, 8, 12],
            "store_addrs": [10000, 0, 10004, 0],
            "throughput_factor": 2,
        },
    )


def gen_QUAD(ORDER, SHIFT):
    """Quad datapath: 4 sine evaluations in parallel, one per column.

    Why it exists: maximum throughput. All 16 PEs across rows 0-2 are active
    (12 compute + EXIT). 4× throughput vs PIPE3 at cost of 13 active PEs.
    Shows the upper bound of spatial parallelism on this CGRA.
    """
    xmi, _, w, mask, _, nc, stride = derived(ORDER, SHIFT)
    segs, _ = fit_segments(ORDER, SHIFT)
    xvals = [round(v * SCALE) for v in [1.0, 2.0, 3.0, 5.0]]
    I = []
    I.append(G({(0, c): "LWD R0" for c in range(4)}))
    I.append(G({(0, c): "LWD R1" for c in range(4)}))
    I.append(G({(0, c): "SSUB R0, R0, R1" for c in range(4)}))
    I.append(G({(0, c): f"SRT R1, R0, {SHIFT}" for c in range(4)}))
    o4 = {}
    for c in range(4):
        o4[(0, c)] = f"LAND R0, R0, {mask}"
        o4[(1, c)] = f"SMUL R0, RCT, {stride}"
    I.append(G(o4))
    o5 = {}
    for c in range(4):
        o5[(1, c)] = f"SADD R1, R0, {LUT_BASE+ORDER*4}"
        o5[(2, c)] = f"SADD R0, RCT, {LUT_BASE}"
    I.append(G(o5))
    I.append(G({(1, c): "LWI R1, R1" for c in range(4)}))
    for k in range(ORDER - 1, -1, -1):
        oa, ob, oc = {}, {}, {}
        for c in range(4):
            oa[(1, c)] = "SMUL R1, R1, RCT"
            oa[(2, c)] = f"SADD ROUT, R0, {k*4}"
        I.append(G(oa))
        for c in range(4):
            ob[(1, c)] = f"SRA R1, R1, {SHIFT}"
            ob[(2, c)] = "LWI R1, ROUT"
        I.append(G(ob))
        for c in range(4):
            oc[(1, c)] = "SADD R1, R1, RCB"
        I.append(G(oc))
    oe = {(1, c): "SWD R1" for c in range(4)}
    oe[(3, 3)] = "EXIT"
    I.append(G(oe))
    mem = []
    for c in range(4):
        mem.append((c * 8, xvals[c]))
        mem.append((c * 8 + 4, xmi))
    for i, cs in enumerate(segs):
        for k, cv in enumerate(cs):
            mem.append((LUT_BASE + i * stride + k * 4, cv))
    a, e, err = horner_check(X_TEST, ORDER, SHIFT, segs, xmi)
    print(f"  QUAD     T{ORDER} S{SHIFT}: {a} exp={e} err={err:.2e}")
    return write(
        "QUAD",
        ORDER,
        SHIFT,
        I,
        mem,
        segs,
        {
            "load_addrs": [0, 8, 16, 24],
            "store_addrs": [10000, 10004, 10008, 10012],
            "throughput_factor": 4,
        },
    )


# ── Runner ─────────────────────────────────────────────────────────
ALL = [
    gen_SEQ,
    gen_PIPE2,
    gen_PIPE3,
    gen_HYBRID,
    gen_LOOP,
    gen_HWAVE,
    gen_QWAVE,
    gen_DUAL,
    gen_QUAD,
]


def run_sweep(ORDER=3, shifts=None):
    if shifts is None:
        shifts = [8, 9, 10, 11, 12]
    os.makedirs("pareto_out", exist_ok=True)
    all_m = []
    for SHIFT in shifts:
        print(f"\n── SHIFT={SHIFT} ──")
        for g in ALL:
            try:
                all_m.append(g(ORDER, SHIFT))
            except Exception as e:
                print(f"  FAIL: {g.__name__}: {e}")
    # summary CSV
    if all_m:
        keys = list(dict.fromkeys(k for m in all_m for k in m.keys()))
        for m in all_m:
            for k in keys:
                m.setdefault(k, "")
        with open("pareto_out/summary.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(all_m)
    print(f"\n{'='*50}")
    print(f"  {len(all_m)} variants generated")
    print(f"  Output: pareto_out/summary.csv")
    print(f"{'='*50}")
    return all_m


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--order", type=int, default=3)
    p.add_argument("--shifts", type=int, nargs="+", default=[8, 9, 10, 11, 12])
    a = p.parse_args()
    run_sweep(a.order, a.shifts)
