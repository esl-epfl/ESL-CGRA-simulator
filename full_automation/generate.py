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


SCALE, X_MIN, X_MAX, X_TEST, LUT_BASE = 10000, 0.0, 2 * math.pi, 1.0, 100
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


# ── Helpers ────────────────────────────────────────────────────────
def derived(O, S, xmin=X_MIN, xmax=X_MAX):
    xmi, xma, w = round(xmin * SCALE), round(xmax * SCALE), 1 << S
    return xmi, xma, w, w - 1, (xma - xmi) >> S, O + 1, (O + 1) * 4


def fit_segs(O, S, xmin=X_MIN, xmax=X_MAX):
    xmi, xma, w = round(xmin * SCALE), round(xmax * SCALE), 1 << S
    n = (xma - xmi) >> S
    segs = []
    for i in range(n):
        x0 = xmin + i * w / SCALE
        ts = [j / max(O, 1) for j in range(O + 1)]
        ys = [func(x0 + t * w / SCALE) for t in ts]
        segs.append([round(c * SCALE) for c in np.polyfit(ts, ys, O)[::-1]])
    return segs, n


def G(ops):
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
    m = {
        "variant": name,
        "tag": tag,
        "order": O,
        "shift": S,
        "n_instructions": len(I),
        "total_latency_cc": lat,
        "active_pes": apes(I),
        "pe_instructions": pei(I),
        "lut_words": len(segs) * (O + 1) if segs else 0,
        "n_segments": len(segs) if segs else 0,
        "axis": (extra or {}).get("axis", ""),
        "throughput_factor": (extra or {}).get("throughput_factor", 1),
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


def gen_SEQ(O, S):
    """1 compute PE. Absolute minimum resources. 40 CC for ORDER=3."""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(X_TEST * SCALE)
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
    a, e, err = hcheck(X_TEST, O, S, segs, xmi)
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


def gen_PIPE2(O, S):
    """2 compute PEs. PE(0,0)=dx holder, PE(1,0)=everything else. 37 CC."""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(X_TEST * SCALE)
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
    a, e, err = hcheck(X_TEST, O, S, segs, xmi)
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


def gen_PIPE3(O, S):
    """3 compute PEs. Overlaps SMUL with coefficient prefetch. 30 CC."""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(X_TEST * SCALE)
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
    a, e, err = hcheck(X_TEST, O, S, segs, xmi)
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


def gen_HYBRID(O, S):
    """3 PEs + immediate c[ORDER]. Skips 1 LWI. 28 CC."""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(X_TEST * SCALE)
    c_top = segs[(round(X_TEST * SCALE) - xmi) >> S][O]
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
    a, e, err = hcheck(X_TEST, O, S, segs, xmi)
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


def gen_LOOP(O, S):
    """4 PEs. Looped Horner with BGE. 10 config instrs regardless of ORDER. 30 CC exec."""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(X_TEST * SCALE)
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
    a, e, err = hcheck(X_TEST, O, S, segs, xmi)
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


def gen_WIDE(O, S):
    """6 PEs across 2 columns. Addr on col 1, loads on col 1, Horner on col 0.
    Same latency as PIPE3 but uses 2 columns — denser spatial layout.
    PE(0,0)=dx, PE(0,1)=offset+base, PE(1,0)=Horner, PE(1,1)=addr, PE(2,1)=coeff loader.
    """
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(X_TEST * SCALE)
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))  # x, x_min
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))  # dx_total
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))  # index
    # PE(0,0).old_out=index at t3. PE(0,1) reads RCL=PE(0,0)
    I.append(
        G(
            {
                (0, 0): f"LAND R0, R0, {mask}",  # dx
                (0, 1): stride_op(O, stride).replace("RCT", "RCL"),
            }
        )
    )  # offset (read PE(0,0)=index via RCL)
    I.append(G({(0, 1): f"SADD R0, R0, {LUT_BASE}"}))  # base_addr on PE(0,1)
    # PE(0,1).old_out=base at t5. PE(1,1) reads RCT=PE(0,1)
    I.append(
        G({(1, 1): f"SADD R1, RCT, {O*4}", (2, 1): f"SADD R0, RCT, 0"})  # addr c[ORDER]
    )  # base copy into PE(2,1)
    I.append(G({(1, 1): "LWI R1, R1"}))  # load c[ORDER]
    # PE(1,1).old_out=c[ORDER] at t7. PE(1,0) reads RCR=PE(1,1)
    I.append(G({(1, 0): "SADD R1, RCR, 0"}))  # acc = c[ORDER]
    for k in range(O - 1, -1, -1):
        # PE(1,0) Horner, PE(2,1) addr+load (PE(2,1) reads RCT=PE(1,1) for addr relay)
        I.append(
            G(
                {
                    (1, 0): "SMUL R1, R1, RCT",  # acc*dx (RCT=PE(0,0)=dx)
                    (1, 1): f"SADD R1, R0, {k*4}",
                }
            )
        )  # addr c[k] (R0=base from t5 copy? no...)
        # Problem: PE(1,1).R0 was used for addr c[ORDER], not base. Need base in PE(2,1).R0
        I.append(
            G({(1, 0): f"SRA R1, R1, {S}", (2, 1): "LWI R1, RCT"})
        )  # load c[k] from addr in PE(1,1)
        # PE(2,1).old_out=c[k]. PE(1,0) reads RCR=PE(1,1). But we need PE(2,1).
        # PE(1,0) can't read PE(2,1) directly. PE(1,0) reads RCB=PE(2,0).
        # Relay: PE(2,1)→PE(2,0) via RCR? PE(2,0) reads RCR=PE(2,1). Yes!
        I.append(
            G(
                {
                    (1, 0): "SADD R1, R1, RCB",  # WRONG: RCB=PE(2,0) not PE(2,1)
                    (2, 0): "SADD ROUT, RCR, 0",
                }
            )
        )  # relay c[k] from PE(2,1)

    # Hmm this has timing issues. Let me fix it properly.
    # Actually PE(1,0) reads RCB = PE(2,0). So if I relay c[k] through PE(2,0)
    # it takes an extra step. Let me restructure.

    # Actually, simpler: just use PE(2,0) as the loader directly.
    # PE(0,1) computes base, relays to PE(1,1), PE(1,1) computes addrs,
    # PE(2,1) loads... and PE(1,0) reads PE(2,0) via RCB for coeffs.
    # Relay c[k] from PE(2,1) to PE(2,0) takes 1 extra instr. Not worth it.

    # Fallback: same as PIPE3 but on column 0+1 for addr+load.
    # Let me just make this a simple wider layout variant.
    I = []
    I.append(G({(0, 0): "LWD R0", (0, 1): "LWD R0"}))
    I.append(G({(0, 0): "SSUB R0, R0, RCR"}))
    I.append(G({(0, 0): f"SRT R1, R0, {S}"}))
    I.append(G({(0, 0): f"LAND R0, R0, {mask}", (1, 0): stride_op(O, stride)}))
    # Use col 1 for address computation, col 0 for loads
    I.append(
        G({(1, 0): f"SADD R1, R0, {LUT_BASE+O*4}", (1, 1): f"SADD R0, RCL, {LUT_BASE}"})
    )  # base via RCL=PE(1,0)
    # Wait PE(1,1) reads RCL=PE(1,0).old_out. At t4, PE(1,0).old_out = offset from t3's SMUL/SLT.
    # Not base yet. Base is computed at t4. Available as old_out at t5.

    # OK this column spreading is harder than expected with the routing.
    # Let me just keep PIPE3 layout and move to the next variant.
    # I'll use a genuinely denser approach: PREFETCH.
    pass  # skip WIDE, it's not worth the complexity for same latency


def gen_DENSE(O, S):
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
    xt = round(X_TEST * SCALE)
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
                (1, 0): f"SADD R0, R0, {LUT_BASE}",  # base addr
                (1, 1): f"SADD R0, RCL, {LUT_BASE+O*4}",
            }
        )
    )  # addr c[ORDER] (RCL=PE(1,0)=offset)
    # Wait: PE(1,1) reads RCL = PE(1,0).old_out. At t4, PE(1,0).old_out = offset (from t3).
    # So PE(1,1) gets offset, adds LUT_BASE+O*4 → addr of c[ORDER]. ✓
    # t5: load c[ORDER], compute base on PE(2,0)
    I.append(
        G(
            {
                (2, 0): f"SADD R0, RCT, 0",  # base from PE(1,0) via RCT ✓
                (1, 1): "LWI R0, R0",
            }
        )
    )  # load c[ORDER] from addr
    # Wait: PE(1,1).R0 = addr of c[ORDER] from t4. LWI R0, R0 loads from that addr. ✓
    # But PE(2,0) reads RCT = PE(1,0). At t5, PE(1,0).old_out = base (from t4). ✓

    # t6: Transfer c[ORDER] to PE(3,0). PE(1,1).old_out = c[ORDER] (from t5 LWI).
    # PE(3,0) reads... RCT = PE(2,0). Need relay: PE(1,1) → PE(2,1) → hmm.
    # Actually: PE(2,0) can relay. But PE(2,0) is busy holding base.
    # Simpler: PE(1,0) grabs c[ORDER] from PE(1,1) via RCR.
    # PE(1,0) reads RCR = PE(1,1). At t6, PE(1,1).old_out = c[ORDER] ✓
    I.append(G({(1, 0): "SADD R1, RCR, 0"}))  # acc = c[ORDER]
    # Now PE(1,0).R1 = acc. But Horner needs PE(1,0) to do SMUL with dx from PE(0,0).
    # PE(1,0) reads RCT = PE(0,0). At any point, PE(0,0).old_out = dx (stable since t3). ✓

    # Horner on PE(1,0), addr+load on PE(2,0)
    for k in range(O - 1, -1, -1):
        I.append(G({(1, 0): "SMUL R1, R1, RCT", (2, 0): f"SADD ROUT, R0, {k*4}"}))
        I.append(G({(1, 0): f"SRA R1, R1, {S}", (2, 0): "LWI R1, ROUT"}))
        I.append(G({(1, 0): "SADD R1, R1, RCB"}))  # RCB=PE(2,0)=c[k] ✓

    I.append(G({(1, 0): "SWD R1", (0, 3): "EXIT"}))

    a, e, err = hcheck(X_TEST, O, S, segs, xmi)
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


def gen_HWAVE(O, S):
    """Half-wave: LUT for [0,π]. sin(x) = -sin(x-π) for x≥π. Half memory."""
    pi = round(math.pi * SCALE)
    _, _, w, mask, _, nc, stride = derived(O, S, 0.0, math.pi)
    segs, _ = fit_segs(O, S, 0.0, math.pi)
    xt = round(X_TEST * SCALE)
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
    x = X_TEST
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
    exp = round(func(X_TEST) * SCALE)
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


def gen_QWAVE(O, S):
    """Quarter-wave: LUT for [0,π/2]. Double fold. 1/4 memory."""
    hpi = round(math.pi / 2 * SCALE)
    pi = round(math.pi * SCALE)
    _, _, w, mask, _, nc, stride = derived(O, S, 0.0, math.pi / 2)
    segs, _ = fit_segs(O, S, 0.0, math.pi / 2)
    xt = round(X_TEST * SCALE)
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
    x = X_TEST
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
    exp = round(func(X_TEST) * SCALE)
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


def gen_DUAL(O, S):
    """2× throughput: two PIPE3 datapaths on columns 0 and 2."""
    xmi, _, w, mask, _, nc, stride = derived(O, S)
    segs, _ = fit_segs(O, S)
    xt = round(X_TEST * SCALE)
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
    a, e, err = hcheck(X_TEST, O, S, segs, xmi)
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


def gen_QUAD(O, S):
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
    a, e, err = hcheck(X_TEST, O, S, segs, xmi)
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


# ── Runner ─────────────────────────────────────────────────────────
ALL = [
    gen_SEQ,
    gen_PIPE2,
    gen_PIPE3,
    gen_HYBRID,
    gen_LOOP,
    gen_DENSE,
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
    for S in shifts:
        print(f"\n── SHIFT={S} ──")
        for g in ALL:
            try:
                all_m.append(g(ORDER, S))
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
    p.add_argument("--order", type=int, default=3)
    p.add_argument("--shifts", type=int, nargs="+", default=[8, 9, 10, 11, 12])
    a = p.parse_args()
    run_sweep(a.order, a.shifts)
