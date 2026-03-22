# CGRA Sine Approximation — Pareto Design Space

9 architecture variants for piecewise polynomial sine on the ESL-CGRA.
Each trades off latency, PE count, LUT memory, and configuration size differently.

## Quick start

```bash
python generate.py                # 9 variants × 5 SHIFTs = 45 outputs
python plot.py                    # 2 clean Pareto graphs (SHIFT=10)
python dataflow_gen.py pareto_out/PIPE3_T3_S10   # DOT dataflow graph
```

## How the computation works

We approximate `sin(x)` using **piecewise polynomial interpolation**:

1. The input range is split into segments of width `2^SHIFT` (power-of-2 so we can divide with bit shifts instead of actual division)
2. For each segment, we pre-fit a degree-ORDER polynomial offline (on your PC) and store the coefficients in a lookup table in SRAM
3. At runtime, the CGRA:
   - Finds which segment `x` falls in (index = `(x − x_min) >> SHIFT`)
   - Computes how far into the segment (`dx = (x − x_min) & mask`)
   - Loads the segment's coefficients from the LUT
   - Evaluates `y = c₀ + c₁·(dx/w) + c₂·(dx/w)² + ...` using **Horner's method**: start with `acc = c[ORDER]`, then for k from ORDER-1 down to 0: `acc = (acc × dx >> SHIFT) + c[k]`

The `>> SHIFT` replaces division by segment width. All arithmetic is integer (`SMUL` + `SRA`), values scaled by `SCALE=10000`.

## The 9 variants

### Axis 1: Pipeline depth (how many PEs work in parallel)

**SEQ** — *Everything on one PE.*
Minimum resources (2 PEs: PE(0,0) + EXIT). Every Horner step is 5 serial instructions because we can't overlap multiply with coefficient loading. The slowest variant.
```
PE(0,0): load → subtract → shift → mask → [mul → shift → addr → load → add] × ORDER → store
PE(0,3): EXIT
```

**PIPE2** — *2-PE pipeline.*
PE(0,0) computes dx once and holds it in its output forever. PE(1,0) reads dx via `RCT` whenever it needs it for `SMUL`. One less register used on PE(1,0), but coefficient loads are still serial. 5 instrs per Horner iteration.

**PIPE3** — *3-PE pipeline. THE BASELINE.*
The key design. While PE(1,0) is doing `SMUL` (which takes 3 clock cycles), PE(2,0) computes the next coefficient address and starts loading it from SRAM. By the time PE(1,0) finishes `SMUL → SRA`, the coefficient is ready in PE(2,0)'s output. **Only 3 instructions per Horner iteration** instead of 5.
```
PE(0,0): computes dx, holds it stable
PE(1,0): Horner accumulator (SMUL → SRA → SADD each iteration)
PE(2,0): coefficient prefetcher (SADD addr → LWI in parallel with PE(1,0))
PE(0,3): EXIT
```

**HYBRID** — *Fastest general-purpose variant.*
Same as PIPE3 but the top coefficient `c[ORDER]` is embedded as an immediate value in the instruction instead of being loaded from SRAM. Skips one `LWI` in the setup phase. Saves 2 clock cycles vs PIPE3. Still works for any input x — the remaining coefficients still come from the LUT at runtime.

### Axis 2: Control flow (unrolled vs looped)

**LOOP** — *Compact configuration.*
The 3-instruction Horner iteration is expressed as a loop with `BGE` (branch if greater or equal) instead of being unrolled. PE(3,0) runs a counter; PE(2,0) decrements the coefficient address by 4 each iteration.

Result: 10 instructions to configure regardless of ORDER, vs 7 + 3×ORDER for PIPE3 (16 for ORDER=3). Same execution latency. Saves configuration memory at the cost of 1 extra PE for the loop counter.

### Axis 3: LUT memory (exploiting sine symmetry)

**HWAVE** — *Half-wave symmetry.*
`sin(x) = −sin(x − π)` for x ≥ π. Only stores coefficients for [0, π]. Before the Horner evaluation, a folding phase checks whether x ≥ π and if so: uses `x − π` as the input and multiplies the result by −1. The conditional fold uses `BSFA` (select based on sign flag). Halves the LUT memory, costs ~9 extra instructions.

**QWAVE** — *Quarter-wave symmetry.*
`sin(x) = sin(π − x)` for x ∈ [π/2, π]. Combined with the half-wave fold, only stores coefficients for [0, π/2] — one quarter of the full LUT. Two BSFA operations: first fold around π, then fold around π/2. Costs ~12 extra instructions but cuts LUT to 1/4.

### Axis 4: Throughput (spatial parallelism)

**DUAL** — *2× throughput.*
Two independent PIPE3 datapaths running in parallel on columns 0 and 2. Each column has its own dx/Horner/loader pipeline. They share the same LUT in SRAM (indirect loads go to the same memory). Processes two x values per invocation.

**QUAD** — *4× throughput.*
Four independent PIPE3 datapaths, one per column. All 12 compute PEs active (rows 0-2 × cols 0-3). Maximum throughput the CGRA can deliver.

## SHIFT parameter

SHIFT controls the segment width = 2^SHIFT scaled integer units:

| SHIFT | Segments (full wave) | LUT words (ORDER=3) | Segment width |
|-------|---------------------|---------------------|---------------|
| 8     | 245                 | 980                 | 256           |
| 9     | 122                 | 488                 | 512           |
| 10    | 61                  | 244                 | 1024          |
| 11    | 30                  | 120                 | 2048          |
| 12    | 15                  | 60                  | 4096          |

Larger SHIFT = fewer segments = less memory, but slightly lower accuracy for high-ORDER polynomials. For ORDER=3 the error stays below 2×10⁻⁴ across all SHIFT values.

## Pareto front summary (SHIFT=10, ORDER=3)

### Latency vs Resources
```
Variant      PEs  Latency  Why it's on the front
─────────────────────────────────────────────────
HYBRID        5    28 CC   Fastest (immediate top coeff)
PIPE3         5    30 CC   Baseline (reference design)
LOOP          6    30 CC   Same speed, smallest config (10 instrs)
PIPE2         4    37 CC   One fewer PE than PIPE3
SEQ           2    40 CC   Minimum PEs possible
```

### Latency vs Memory
```
Variant      LUT   Latency  Why it's on the front
──────────────────────────────────────────────────
HYBRID       244    28 CC   Fastest with full LUT
HWAVE        120    39 CC   Half memory (−11 CC cost)
QWAVE         60    45 CC   Quarter memory (−17 CC cost)
```

## CGRA routing reference

PE(r,c) reads its neighbors' **previous cycle output** via:
```
RCT → PE(r−1, c)   top     (wraps: row 0 reads row 3)
RCB → PE(r+1, c)   bottom  (wraps: row 3 reads row 0)
RCL → PE(r, c−1)   left    (wraps: col 0 reads col 3)
RCR → PE(r, c+1)   right   (wraps: col 3 reads col 0)
```

Each PE has 4 registers (R0-R3), an output visible to neighbors, and executes one instruction per clock cycle.

## ISA quick reference

| Op | Does | Cycles | Notes |
|----|------|--------|-------|
| SADD dst, a, b | dst = a + b | 1 | |
| SSUB dst, a, b | dst = a − b | 1 | |
| SMUL dst, a, b | dst = a × b | 3 | int32, no widening |
| SRT dst, a, n | dst = a >>> n | 1 | logical (unsigned) right shift |
| SRA dst, a, n | dst = a >> n | 1 | arithmetic (signed) right shift |
| LAND dst, a, b | dst = a & b | 1 | bitwise AND |
| LWD dst | dst = mem[addr++] | 2 | sequential load, auto-increment |
| SWD src | mem[addr++] = src | 2 | sequential store |
| LWI dst, addr | dst = mem[addr] | 2 | indirect load (computed address) |
| SWI src, addr | mem[addr] = src | 2 | indirect store |
| BSFA dst, a, b, flag | dst = sign(flag)? a : b | 1 | conditional select |
| BGE a, b, target | if a ≥ b: jump | 1 | branch |
| EXIT | halt | 2 | |

Sources: R0-R3, RCT/RCB/RCL/RCR (neighbor output), ZERO, integer immediate.

## File structure

```
generate.py      — generates all 9 variants × N SHIFTs
plot.py          — two Pareto scatter plots
dataflow_gen.py  — DOT graph per variant (read top→bottom = time)
pareto_out/
  summary.csv    — master metrics table
  plots/         — PNG files
  <VARIANT>_T<ORDER>_S<SHIFT>/
    instructions.csv  — feed to the ESL-CGRA simulator
    memory.csv        — initial memory (inputs + LUT)
    metrics.json      — latency, PE count, LUT size, etc.
    dataflow.dot      — Graphviz diagram
```