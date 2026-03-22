"""
Per-axis Pareto plots.  Latency always on X axis.

  Plot 1: Pipeline axis    — Latency vs Active PEs (for full-wave variants)
  Plot 2: Memory axis      — Latency vs LUT words (SHIFT sweep gives the curve!)
  Plot 3: Throughput axis  — Latency vs Throughput (evals per invocation)

Usage:  python plot.py [--shift 10]
"""

import csv, os, argparse, matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def plot_axis(pts, x_key, y_key, xlabel, ylabel, title, path, annotate=True):
    xs = [p[x_key] for p in pts]
    ys = [p[y_key] for p in pts]
    labels = [p.get("_label", p.get("variant", "")) for p in pts]

    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.scatter(xs, ys, s=80, c="#1565C0", zorder=3, edgecolors="white", linewidth=0.5)

    # Pareto front (minimize both x and y)
    indexed = sorted(enumerate(zip(xs, ys)), key=lambda t: (t[1][0], t[1][1]))
    front = []
    best_y = float("inf")
    for idx, (x, y) in indexed:
        if y < best_y:
            front.append(idx)
            best_y = y
    if len(front) >= 2:
        fpts = sorted([(xs[i], ys[i]) for i in front])
        fx, fy = zip(*fpts)
        ax.plot(fx, fy, "k-", alpha=0.4, linewidth=2, zorder=2)
        ax.scatter(
            fx,
            fy,
            s=200,
            facecolors="none",
            edgecolors="#E53935",
            linewidth=2.5,
            zorder=4,
        )

    if annotate:
        for i in range(len(xs)):
            ax.annotate(
                labels[i],
                (xs[i], ys[i]),
                fontsize=8,
                xytext=(6, 4),
                textcoords="offset points",
            )

    ax.set_xlabel(xlabel, fontsize=13)
    ax.set_ylabel(ylabel, fontsize=13)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close()
    print(f"  {path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="pareto_out/summary.csv")
    p.add_argument("--shift", type=int, default=10)
    a = p.parse_args()

    rows = load(a.input)
    os.makedirs("pareto_out/plots", exist_ok=True)
    O = rows[0]["order"]

    # ── Plot 1: Pipeline axis (SHIFT fixed, full-wave only) ──
    pipe_rows = [
        r for r in rows if int(r["shift"]) == a.shift and r["axis"] in ("pipeline", "")
    ]
    # Deduplicate
    seen = {}
    for r in pipe_rows:
        key = (int(r["total_latency_cc"]), int(r["active_pes"]))
        if key not in seen:
            seen[key] = r
            r["_label"] = r["variant"]
        else:
            seen[key]["_label"] += " / " + r["variant"]
    pipe_pts = [
        {
            "_label": p["_label"],
            "x": int(p["total_latency_cc"]),
            "y": int(p["active_pes"]),
        }
        for p in seen.values()
    ]
    plot_axis(
        pipe_pts,
        "x",
        "y",
        "Latency (clock cycles)",
        "Active PEs",
        f"Pipeline Axis — Latency vs PEs  (ORDER={O}, SHIFT={a.shift})",
        "pareto_out/plots/axis_pipeline.png",
    )

    # ── Plot 2: Memory axis (ALL SHIFTS, one line per architecture) ──
    # For each variant that has a memory axis or is PIPE3 baseline,
    # plot all SHIFT values. Each SHIFT gives different LUT size.
    mem_variants = {"PIPE3", "HYBRID", "HWAVE", "QWAVE"}
    mem_rows = [r for r in rows if r["variant"] in mem_variants]
    mem_pts = [
        {
            "_label": f"{r['variant']} S{r['shift']}",
            "variant": r["variant"],
            "x": int(r["total_latency_cc"]),
            "y": int(r["lut_words"]),
            "shift": int(r["shift"]),
        }
        for r in mem_rows
    ]

    fig, ax = plt.subplots(figsize=(10, 6.5))
    colors = {
        "PIPE3": "#1565C0",
        "HYBRID": "#2E7D32",
        "HWAVE": "#E65100",
        "QWAVE": "#AD1457",
    }
    for var in mem_variants:
        vpts = sorted([p for p in mem_pts if p["variant"] == var], key=lambda p: p["x"])
        if vpts:
            ax.plot(
                [p["x"] for p in vpts],
                [p["y"] for p in vpts],
                "o-",
                color=colors[var],
                label=var,
                markersize=7,
                linewidth=2,
            )
            for p in vpts:
                ax.annotate(
                    f"S{p['shift']}",
                    (p["x"], p["y"]),
                    fontsize=7,
                    xytext=(4, 4),
                    textcoords="offset points",
                    color=colors[var],
                )
    ax.set_xlabel("Latency (clock cycles)", fontsize=13)
    ax.set_ylabel("LUT words (SRAM memory)", fontsize=13)
    ax.set_title(
        f"Memory Axis — Latency vs LUT size  (ORDER={O}, all SHIFTs)",
        fontsize=14,
        fontweight="bold",
    )
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.2)
    fig.tight_layout()
    fig.savefig("pareto_out/plots/axis_memory.png", dpi=150)
    plt.close()
    print(f"  pareto_out/plots/axis_memory.png")

    # ── Plot 3: Throughput axis (SHIFT fixed) ──
    tp_variants = {"PIPE3", "DUAL", "QUAD"}
    tp_rows = [
        r for r in rows if int(r["shift"]) == a.shift and r["variant"] in tp_variants
    ]
    tp_pts = [
        {
            "_label": f"{r['variant']} ({r.get('throughput_factor',1)}×)",
            "x": int(r["total_latency_cc"]),
            "y": int(r["active_pes"]),
        }
        for r in tp_rows
    ]
    plot_axis(
        tp_pts,
        "x",
        "y",
        "Latency (clock cycles)",
        "Active PEs",
        f"Throughput Axis — Latency vs PEs  (ORDER={O}, SHIFT={a.shift})",
        "pareto_out/plots/axis_throughput.png",
    )


if __name__ == "__main__":
    main()
