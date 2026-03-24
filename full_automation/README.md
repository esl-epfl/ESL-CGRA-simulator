# CGRA Sine Approximation — Design Space and Mathematical Rationale

This project studies how the **same numerical task** — evaluating `sin(x)` in fixed-point arithmetic — can be mapped onto a **4×4 ESL-CGRA** in very different ways.

The current generator explores **15 variants** across four axes: pipeline structure, memory reduction, throughput scaling, and sine-specific algorithms. The active variant list in `generate.py` is: `SEQ`, `PIPE2`, `PIPE3`, `HYBRID`, `LOOP`, `WIDE`, `DENSE`, `HWAVE`, `QWAVE`, `DUAL`, `QUAD`, `STAGGERED_QUAD`, `DERIV1`, `DERIV3`, and `DERIV3_QWAVE`. 

---

## 1. The baseline mathematical model

All baseline variants start from the same idea: approximate `sin(x)` by a **piecewise polynomial** over a fixed interval.

The input is represented in fixed-point:

\[
x_i = \operatorname{round}(x \cdot \text{SCALE}), \qquad \text{SCALE}=10000
\]

The full-wave baseline uses the domain:

\[
[0, 2\pi]
\]

and splits it into segments of width

\[
w = 2^S
\]

where `S` is the `SHIFT` parameter. The helper `derived(O, S)` makes this explicit: it computes the segment width `w = 1 << S`, the mask `w - 1`, the number of segments, and the per-segment memory stride `(O+1) * 4`. fileciteturn17file9

For each segment, `fit_segs(O, S)` samples `sin(x)` at `O+1` points, fits a degree-`O` polynomial offline with `np.polyfit`, and stores the coefficients in fixed-point form. fileciteturn17file9

So for segment `i`, the hardware is not trying to compute the exact transcendental function directly. It is evaluating a local approximation

\[
p_i(t)=c_0+c_1 t+c_2 t^2+\dots+c_O t^O
\]

with a normalized local variable

\[
t = \frac{dx}{2^S}.
\]

---

## 2. How the input is decomposed

Let

\[
d = x_i - x_{\min}.
\]

The hardware splits this into two parts:

\[
\text{idx} = d \gg S
\]
\[
dx = d \;\&\; (2^S-1)
\]

This is the key fixed-point trick.

- `idx` is the **segment index**
- `dx` is the **local position inside that segment**

and together they satisfy

\[
d = \text{idx} \cdot 2^S + dx.
\]

So when you see `SRT R1, R0, S` and then `LAND R0, R0, mask`, the hardware is not doing two unrelated operations. It is splitting the input into:

1. “which polynomial should I use?”
2. “where am I inside that polynomial’s interval?”

This is why `S8` uses more memory than `S12`: smaller segment width means more segments across the same domain. Since the number of segments scales roughly like

\[
N_{\text{seg}} \approx \frac{x_{\max}-x_{\min}}{2^S},
\]

smaller `S` means larger LUTs, and larger `S` means fewer segment records. fileciteturn17file9

---

## 3. Why Horner’s method is the right hardware form

A direct polynomial implementation would require explicit powers of `t`:

\[
c_0 + c_1 t + c_2 t^2 + c_3 t^3.
\]

That is mathematically fine, but hardware-unfriendly.

Instead, all baseline polynomial variants use **Horner’s form**:

\[
p(t)=c_0+t(c_1+t(c_2+\dots+t c_O)).
\]

This turns the whole evaluation into a short recurrence:

\[
\text{acc} \leftarrow c_O
\]
\[
\text{acc} \leftarrow (\text{acc} \cdot t) + c_k
\qquad k=O-1,\dots,0.
\]

But the hardware does not store `t`; it stores `dx`, and since

\[
t = \frac{dx}{2^S},
\]

each multiply by `t` becomes

\[
(\text{acc} \cdot dx) \gg S.
\]

That is why the Horner loop always has the same mathematical shape:

\[
\text{acc} \leftarrow ((\text{acc} \cdot dx) \gg S) + c_k.
\]

This single recurrence explains the structure of `SEQ`, `PIPE2`, `PIPE3`, `HYBRID`, `LOOP`, `WIDE`, and `DENSE`. They differ mainly in **where the recurrence lives** and **how coefficient fetches are overlapped**, not in what they compute. fileciteturn17file0turn17file12turn17file11

---

## 4. Pen-and-paper walkthrough: `SEQ`

`SEQ` is the cleanest variant to understand because it is almost a direct translation of the mathematics into instructions.

Take a cubic segment:

\[
p(t)=c_0 + c_1 t + c_2 t^2 + c_3 t^3
\]

Rewrite it in Horner form:

\[
p(t)=c_0 + t(c_1 + t(c_2 + t c_3)).
\]

Now follow the execution conceptually.

### Step 1 — shift the input into the LUT domain

The PE loads `x` and `x_min`, then computes

\[
d = x - x_{\min}.
\]

This moves the input into the approximation domain.

### Step 2 — find the segment

The PE computes

\[
\text{idx} = d \gg S.
\]

This is integer division by the segment width. It tells the hardware which coefficient block to fetch from SRAM.

### Step 3 — find the local offset

The PE computes

\[
dx = d \;\&\; (2^S-1).
\]

This keeps the low `S` bits, i.e. the local position inside the chosen segment.

### Step 4 — compute the segment base address

If a segment stores `O+1` coefficients, and each coefficient is 4 bytes, then one segment occupies

\[
\text{stride} = (O+1) \cdot 4
\]

bytes.

So the base address of segment `idx` is

\[
\text{base} = \text{LUT\_BASE} + \text{idx}\cdot\text{stride}.
\]

For `O=3`, one segment in memory looks like:

| Address offset | Content |
|---:|---|
| `base + 0`  | `c0` |
| `base + 4`  | `c1` |
| `base + 8`  | `c2` |
| `base + 12` | `c3` |

### Step 5 — evaluate the polynomial

The PE starts from the highest coefficient:

\[
\text{acc} = c_3.
\]

Then it applies the Horner recurrence three times:

\[
\text{acc} = ((c_3 \cdot dx) \gg S) + c_2
\]
\[
\text{acc} = ((\text{acc} \cdot dx) \gg S) + c_1
\]
\[
\text{acc} = ((\text{acc} \cdot dx) \gg S) + c_0.
\]

The final value is the sine approximation for that segment.

### Why the right shift is mathematically correct

Because the polynomial is written in terms of

\[
t = \frac{dx}{2^S},
\]

every time the recurrence says “multiply by `t`”, the hardware can instead multiply by `dx` and divide by `2^S`. Since `2^S` is a power of two, division becomes a right shift.

### Why `SEQ` is slow

`SEQ` performs everything on one PE:

- input reduction
- address generation
- coefficient loads
- multiply
- rescaling
- add
- store

So there is no overlap between computation and memory access. It is the best pen-and-paper reference because it is simple, but it is the worst latency baseline. fileciteturn17file0

---

## 5. What the pipeline variants are really changing

The pipeline family all computes the same polynomial, but changes the **schedule**.

### `PIPE2`
`PIPE2` splits the work into two roles:

- one PE computes and holds `dx`
- one PE performs address generation and Horner evaluation

This removes some register pressure from the accumulator PE, but coefficient fetches are still largely serialized. fileciteturn17file0

### `PIPE3`
`PIPE3` is the reference architecture. It adds a third PE so that coefficient fetches overlap with Horner arithmetic:

- PE A holds `dx`
- PE B holds the Horner accumulator
- PE C computes the next coefficient address and loads it while PE B is still busy multiplying

This is the key scheduling idea of the project: exploit the 3-cycle latency of `SMUL` by using that time to prefetch the next coefficient. fileciteturn17file0

### `HYBRID`
`HYBRID` keeps the same core structure as `PIPE3`, but avoids the initial top-coefficient load by embedding the highest coefficient as an immediate. It shortens the setup phase while preserving the rest of the LUT-driven evaluation. fileciteturn17file0

### `LOOP`
`LOOP` keeps the same Horner recurrence but expresses the iteration with a branch-controlled loop. So it trades off configuration size against explicit unrolling. Execution latency is similar to the unrolled versions, but the instruction footprint is more compact. fileciteturn17file12

### `WIDE`
`WIDE` keeps the same functional structure as `PIPE3`, but spreads the address and load logic across two columns. It is a spatial-layout variant rather than a new mathematical method. The important point is that the Horner recurrence still lives in one PE, while neighboring PEs provide `dx` and coefficients through routing. fileciteturn17file12

### `DENSE`
`DENSE` uses more PEs in the setup path so several address computations and relays happen in parallel before the accumulator starts. It does not change the polynomial engine; it reduces slack in the schedule. Its own docstring explicitly describes it as a denser layout with parallel address computation and parallel loading. fileciteturn17file3turn17file11

---

## 6. Memory-reduction variants: exploiting sine symmetry

The memory axis variants are mathematically elegant because they reduce LUT storage without changing the local polynomial engine.

### `HWAVE`
`HWAVE` stores coefficients only over `[0, \pi]` and uses the identity

\[
\sin(x) = -\sin(x-\pi)
\qquad \text{for } x \ge \pi.
\]

So if the input falls in the second half of the period:

1. subtract `π`
2. evaluate the usual segment polynomial on the folded point
3. negate the result

The folding logic adds control overhead, but cuts the LUT roughly in half. The memory for this variant explicitly includes `π` as an extra input constant before the LUT. fileciteturn17file13turn17file18

### `QWAVE`
`QWAVE` goes further and stores coefficients only over `[0, \pi/2]`, using two identities:

\[
\sin(x) = -\sin(x-\pi)
\qquad \text{for } x \ge \pi
\]

and then, inside `[0,\pi]`,

\[
\sin(x)=\sin(\pi-x)
\qquad \text{for } x \in [\pi/2, \pi].
\]

So the front-end folds the input twice:

- first into the correct half-wave
- then into the first quarter-wave

Only then does the polynomial engine run. This makes `QWAVE` one of the strongest memory-saving designs in the baseline family. fileciteturn17file10turn17file17

---

## 7. Throughput variants: replicate instead of shortening

A different way to improve performance is to stop shortening one datapath and instead run several in parallel.

### `DUAL`
`DUAL` instantiates two independent PIPE3-like evaluators. It processes two inputs per invocation and doubles throughput, at the cost of more active PEs and more routing pressure. fileciteturn17file17

### `QUAD`
`QUAD` replicates the same idea across all four columns. It is the maximum straightforward throughput scaling on the 4×4 grid: four independent evaluations share the same global LUT memory but maintain separate local datapaths. fileciteturn17file7

### `STAGGERED_QUAD`
`STAGGERED_QUAD` still uses four lanes, but starts them at staggered times. This does not fundamentally change the arithmetic; it changes the occupancy pattern so the dataflow looks denser and more continuously busy over time. fileciteturn17file8

---

## 8. Algorithm variants: storing less by exploiting sine itself

The most interesting variants are not schedule tweaks but **model changes**.

Instead of storing generic polynomial coefficients per segment, the derivative-based variants exploit the structure of sine:

\[
\sin'(x)=\cos(x), \qquad \sin''(x)=-\sin(x), \qquad \sin'''(x)=-\cos(x).
\]

This means that if you know `sin(x0)` and `cos(x0)` at the start of a segment, you already know enough to reconstruct a local Taylor-like model.

### `DERIV1`
`DERIV1` stores only two words per segment: a value anchor and a slope anchor. Conceptually, it uses a first-order local model

\[
\sin(x_0 + \delta) \approx \sin(x_0) + \delta \cos(x_0).
\]

This is much smaller than a generic polynomial LUT, but it is only linear, so accuracy is lower. fileciteturn17file0

### `DERIV3`
`DERIV3` stores only `[sin(x0), cos(x0)]` per segment, then reconstructs a cubic local approximation using the known derivative pattern of sine. In other words, it spends more arithmetic to avoid storing explicit `c2` and `c3` tables. The implementation also overrides the reported LUT word count to `2 * number_of_segments`, confirming that this is a compressed-memory model. fileciteturn17file4

### `DERIV3_QWAVE`
`DERIV3_QWAVE` combines both ideas:

- quarter-wave symmetry to reduce the domain
- anchor-based cubic reconstruction to reduce per-segment storage

It is one of the most memory-efficient designs in the project because it shrinks both the number of segments and the number of words per segment. The current implementation reports exactly that via `lut_words_override = len(segs) * 2`. fileciteturn17file4turn17file0

---

## 9. Variant summary table

| Variant | Family | Core idea | Main advantage | Main cost |
|---|---|---|---|---|
| `SEQ` | pipeline | one PE does everything | minimum resources | highest latency |
| `PIPE2` | pipeline | isolate `dx` from Horner PE | simpler accumulator PE | limited overlap |
| `PIPE3` | pipeline | overlap Horner and coefficient prefetch | strongest baseline latency/resource point | more PEs than `SEQ` |
| `HYBRID` | pipeline | top coefficient as immediate | shorter setup | still full LUT |
| `LOOP` | pipeline | branch-controlled Horner loop | compact configuration | extra loop control |
| `WIDE` | pipeline | spread the same pipeline across 2 columns | alternate routing layout | not fundamentally faster |
| `DENSE` | pipeline | parallelize more of the setup/address path | denser schedule | higher PE usage |
| `HWAVE` | memory | fold with `π` symmetry | about half LUT memory | extra control/sign logic |
| `QWAVE` | memory | fold with `π` and `π/2` symmetry | about quarter LUT memory | more front-end overhead |
| `DUAL` | throughput | two parallel evaluators | 2× throughput | higher area |
| `QUAD` | throughput | four parallel evaluators | 4× throughput | maximum area |
| `STAGGERED_QUAD` | throughput | same four lanes, staggered launches | denser temporal occupancy | longer global schedule |
| `DERIV1` | algorithm | store anchor + slope only | small LUT | lower accuracy |
| `DERIV3` | algorithm | store only `sin(x0), cos(x0)` | strong memory reduction with good accuracy | more arithmetic |
| `DERIV3_QWAVE` | algorithm | anchor-based cubic + quarter-wave folding | smallest LUT among current methods | most complex control/data path |

---

## 10. SHIFT as the master memory/accuracy knob

`SHIFT` is the global knob that sets the granularity of the approximation.

| SHIFT | Segment width | Segment count | LUT trend |
|---:|---:|---:|---:|
| 8  | 256  | high | large LUT |
| 9  | 512  | lower | smaller |
| 10 | 1024 | lower | smaller |
| 11 | 2048 | low | small |
| 12 | 4096 | very low | very small LUT |

Larger `SHIFT` means each polynomial must approximate sine over a wider interval, which stresses the approximation but shrinks memory. Smaller `SHIFT` means more segments, more memory, and easier local fitting.

---

## 11. Why routing matters so much

The CGRA routing model is simple but decisive:

- `RCT` = top neighbor output
- `RCB` = bottom neighbor output
- `RCL` = left neighbor output
- `RCR` = right neighbor output

Each PE sees the **previous cycle’s** output from its neighbors. That means the real design problem is not just “what arithmetic do I want?” but:

- where do I keep `dx` so that the accumulator can reuse it every iteration?
- where do I compute the next address so that the load returns in time?
- where do I place the Horner accumulator so the recurrence is local and the next coefficient arrives exactly when needed?

That is why `PIPE3` is such an important baseline. It is the first point where the arithmetic structure of Horner matches the communication structure of the array. fileciteturn17file0turn17file12

---

## 12. What this project is really about

This project is best understood as a **mapping study**.

The transcendental function is only the vehicle. The real subject is how one kernel changes character when you optimize for different objectives:

- **minimum PE count** → `SEQ`
- **best scalar latency** → `PIPE3` / `HYBRID`
- **small configuration** → `LOOP`
- **small LUT memory** → `HWAVE`, `QWAVE`, `DERIV3_QWAVE`
- **maximum throughput** → `QUAD`
- **better occupancy / denser schedules** → `DENSE`, `STAGGERED_QUAD`
- **different mathematics, not just different schedules** → `DERIV1`, `DERIV3`, `DERIV3_QWAVE`

So the contribution of the project is not a single “best” sine engine. It is the design space itself: a set of implementations that expose the trade-offs between memory, arithmetic, routing, and spatial parallelism in a very concrete way.
