import argparse
import csv
import os
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

PIPELINE_VARIANTS = ["SEQ", "PIPE2", "PIPE3", "HYBRID", "LOOP", "DENSE"]
MEMORY_VARIANTS = ["PIPE3", "HWAVE", "QWAVE"]
THROUGHPUT_VARIANTS = ["PIPE3", "DUAL", "QUAD", "STAGGERED_QUAD"]


# simple, stable markers to keep plots readable
MARKERS = {
    "SEQ": "o",
    "PIPE2": "s",
    "PIPE3": "^",
    "HYBRID": "D",
    "LOOP": "P",
    "DENSE": "X",
    "HWAVE": "o",
    "QWAVE": "s",
    "DUAL": "o",
    "QUAD": "s",
    "STAGGERED_QUAD": "^",
}


def load_rows(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))

    int_cols = [
        "order",
        "shift",
        "n_instructions",
        "total_latency_cc",
        "active_pes",
        "pe_instructions",
        "lut_words",
        "n_segments",
        "throughput_factor",
    ]
    for r in rows:
        for c in int_cols:
            if c in r and r[c] != "":
                r[c] = int(r[c])
    return rows


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def pareto_min(points, x_key, y_key):
    # minimize x and y
    pts = sorted(points, key=lambda p: (p[x_key], p[y_key]))
    out = []
    best_y = float("inf")
    for p in pts:
        if p[y_key] < best_y:
            out.append(p)
            best_y = p[y_key]
    return out


def annotate_points(ax, pts, label_key, fontsize=8):
    for p in pts:
        ax.annotate(
            str(p[label_key]),
            (p["x"], p["y"]),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=fontsize,
        )


def plot_pipeline(rows, out_dir):
    rows = [r for r in rows if r["variant"] in PIPELINE_VARIANTS]
    shifts = sorted({r["shift"] for r in rows})
    for shift in shifts:
        pts = []
        for r in rows:
            if r["shift"] != shift:
                continue
            pts.append(
                {
                    "x": r["active_pes"],
                    "y": r["total_latency_cc"],
                    "label": r["variant"],
                    "variant": r["variant"],
                }
            )
        if not pts:
            continue

        fig, ax = plt.subplots(figsize=(8.5, 6))
        for p in pts:
            ax.scatter(
                p["x"],
                p["y"],
                s=85,
                marker=MARKERS.get(p["variant"], "o"),
                edgecolors="black",
                linewidth=0.6,
            )
        annotate_points(ax, pts, "label")

        front = pareto_min(pts, "x", "y")
        if len(front) >= 2:
            ax.plot([p["x"] for p in front], [p["y"] for p in front], linewidth=1.5)

        ax.set_xlabel("Active PEs")
        ax.set_ylabel("Latency (clock cycles)")
        ax.set_title(f"Pipeline trade-off — shift S={shift}")
        ax.grid(alpha=0.25)
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"pipeline_shift_S{shift}.png"), dpi=180)
        plt.close(fig)


def plot_memory(rows, out_dir):
    rows = [r for r in rows if r["variant"] in MEMORY_VARIANTS]
    orders = sorted({r["order"] for r in rows})

    for order in orders:
        subset = [r for r in rows if r["order"] == order]
        if not subset:
            continue

        fig, axes = plt.subplots(
            1, len(MEMORY_VARIANTS), figsize=(15, 4.8), sharey=True
        )
        if len(MEMORY_VARIANTS) == 1:
            axes = [axes]

        for ax, variant in zip(axes, MEMORY_VARIANTS):
            vrows = sorted(
                [r for r in subset if r["variant"] == variant],
                key=lambda r: r["lut_words"],
            )
            if not vrows:
                ax.set_visible(False)
                continue

            xs = [r["lut_words"] for r in vrows]
            ys = [r["total_latency_cc"] for r in vrows]
            ax.plot(xs, ys, marker=MARKERS.get(variant, "o"), linewidth=1.8)

            for r in vrows:
                ax.annotate(
                    f"S{r['shift']}",
                    (r["lut_words"], r["total_latency_cc"]),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=8,
                )

            pts = [{"x": x, "y": y} for x, y in zip(xs, ys)]
            front = pareto_min(pts, "x", "y")
            if len(front) >= 2:
                ax.plot(
                    [p["x"] for p in front],
                    [p["y"] for p in front],
                    linestyle="--",
                    linewidth=1.2,
                )

            ax.set_title(variant)
            ax.set_xlabel("LUT words")
            ax.grid(alpha=0.25)

        axes[0].set_ylabel("Latency (clock cycles)")
        fig.suptitle(f"Memory trade-off by architecture — order T={order}")
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"memory_order_T{order}.png"), dpi=180)
        plt.close(fig)


def plot_throughput(rows, out_dir):
    rows = [r for r in rows if r["variant"] in THROUGHPUT_VARIANTS]
    shifts = sorted({r["shift"] for r in rows})
    for shift in shifts:
        subset = [r for r in rows if r["shift"] == shift]
        if not subset:
            continue

        # top: latency vs throughput, bottom: PEs vs throughput
        fig, axes = plt.subplots(2, 1, figsize=(8.5, 8.5), sharex=True)
        for r in subset:
            x = r["throughput_factor"]
            label = r["variant"]
            m = MARKERS.get(label, "o")
            axes[0].scatter(
                x,
                r["total_latency_cc"],
                s=85,
                marker=m,
                edgecolors="black",
                linewidth=0.6,
            )
            axes[0].annotate(
                label,
                (x, r["total_latency_cc"]),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=8,
            )

            axes[1].scatter(
                x, r["active_pes"], s=85, marker=m, edgecolors="black", linewidth=0.6
            )
            axes[1].annotate(
                label,
                (x, r["active_pes"]),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=8,
            )

        axes[0].set_ylabel("Latency (clock cycles)")
        axes[0].set_title(f"Throughput scaling — shift S={shift}")
        axes[0].grid(alpha=0.25)

        axes[1].set_xlabel("Throughput factor")
        axes[1].set_ylabel("Active PEs")
        axes[1].grid(alpha=0.25)

        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"throughput_shift_S{shift}.png"), dpi=180)
        plt.close(fig)


def plot_shift_sweeps(rows, out_dir):
    # One figure per variant. Keeps dense datasets readable.
    variants = sorted({r["variant"] for r in rows})
    for variant in variants:
        vrows = sorted(rows, key=lambda r: (r["order"], r["shift"]))
        vrows = [r for r in vrows if r["variant"] == variant]
        if not vrows:
            continue

        orders = sorted({r["order"] for r in vrows})
        fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8))
        for order in orders:
            o = [r for r in vrows if r["order"] == order]
            if not o:
                continue
            xs = [r["shift"] for r in o]
            axes[0].plot(
                xs,
                [r["total_latency_cc"] for r in o],
                marker="o",
                linewidth=1.6,
                label=f"T{order}",
            )
            axes[1].plot(
                xs,
                [r["lut_words"] for r in o],
                marker="o",
                linewidth=1.6,
                label=f"T{order}",
            )

        axes[0].set_title(f"{variant} — latency vs shift")
        axes[0].set_xlabel("Shift S")
        axes[0].set_ylabel("Latency (clock cycles)")
        axes[0].grid(alpha=0.25)

        axes[1].set_title(f"{variant} — LUT size vs shift")
        axes[1].set_xlabel("Shift S")
        axes[1].set_ylabel("LUT words")
        axes[1].grid(alpha=0.25)
        axes[1].legend(title="Order", fontsize=8)

        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, f"variant_{variant}.png"), dpi=180)
        plt.close(fig)


def plot_architecture_comparisons(rows, out_dir):
    """One figure per (order, shift): easy side-by-side architecture comparison."""
    combos = sorted({(r["order"], r["shift"]) for r in rows})
    for order, shift in combos:
        subset = [r for r in rows if r["order"] == order and r["shift"] == shift]
        if not subset:
            continue

        # Sort once by latency so every panel has the same architecture order.
        subset = sorted(
            subset,
            key=lambda r: (
                r["total_latency_cc"],
                r["active_pes"],
                r["lut_words"],
                r["variant"],
            ),
        )
        names = [r["variant"] for r in subset]
        y = list(range(len(subset)))

        fig, axes = plt.subplots(
            2, 2, figsize=(12.5, max(6.0, 0.55 * len(subset) + 2.5)), sharey=True
        )
        ax_lat, ax_pes = axes[0]
        ax_lut, ax_thr = axes[1]

        latency = [r["total_latency_cc"] for r in subset]
        pes = [r["active_pes"] for r in subset]
        lut = [r["lut_words"] for r in subset]
        thr = [r.get("throughput_factor", 1) for r in subset]

        ax_lat.barh(y, latency)
        ax_pes.barh(y, pes)
        ax_lut.barh(y, lut)
        ax_thr.barh(y, thr)

        for ax, vals, title, xlabel in [
            (ax_lat, latency, "Latency", "Clock cycles"),
            (ax_pes, pes, "Active PEs", "Count"),
            (ax_lut, lut, "LUT size", "Words"),
            (ax_thr, thr, "Throughput", "Factor"),
        ]:
            ax.set_title(title)
            ax.set_xlabel(xlabel)
            ax.grid(axis="x", alpha=0.25)
            for yi, v in zip(y, vals):
                ax.text(v, yi, f" {v}", va="center", fontsize=8)

        ax_lat.set_yticks(y)
        ax_lat.set_yticklabels(names)
        ax_pes.set_yticks(y)
        ax_lut.set_yticks(y)
        ax_thr.set_yticks(y)

        # Best values highlighted by panel title note.
        best_lat = min(latency)
        best_pes = min(pes)
        best_lut = min(lut)
        best_thr = max(thr)
        fig.suptitle(
            f"Architecture comparison — T={order}, S={shift}\nBest: latency={best_lat}, PEs={best_pes}, LUT={best_lut}, throughput={best_thr}",
            fontsize=12,
        )
        fig.tight_layout()
        fig.savefig(
            os.path.join(out_dir, f"architecture_T{order}_S{shift}.png"), dpi=180
        )
        plt.close(fig)


def plot_architecture_overview(rows, out_dir):
    """Compact overview: one heatmap-like panel per metric across all T/S combos."""
    variants = sorted({r["variant"] for r in rows})
    combos = sorted({(r["order"], r["shift"]) for r in rows})
    combo_labels = [f"T{o} S{s}" for o, s in combos]

    metrics = [
        ("total_latency_cc", "Latency (cc)"),
        ("active_pes", "Active PEs"),
        ("lut_words", "LUT words"),
        ("throughput_factor", "Throughput"),
    ]

    fig, axes = plt.subplots(
        len(metrics),
        1,
        figsize=(max(12, 0.6 * len(combos) + 2), max(8, 1.6 * len(metrics))),
        sharex=True,
    )
    if len(metrics) == 1:
        axes = [axes]

    for ax, (metric, title) in zip(axes, metrics):
        for i, variant in enumerate(variants):
            vals = []
            for combo in combos:
                matches = [
                    r
                    for r in rows
                    if r["variant"] == variant and (r["order"], r["shift"]) == combo
                ]
                vals.append(matches[0][metric] if matches else None)
            xs = [j for j, v in enumerate(vals) if v is not None]
            ys = [vals[j] for j in xs]
            if xs:
                ax.plot(xs, ys, marker="o", linewidth=1.4, label=variant)
        ax.set_ylabel(title)
        ax.grid(alpha=0.25)
        ax.legend(ncol=min(4, len(variants)), fontsize=8)

    axes[-1].set_xticks(range(len(combo_labels)))
    axes[-1].set_xticklabels(combo_labels, rotation=45, ha="right")
    axes[0].set_title("Architecture overview across all orders and shifts")
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "architecture_overview.png"), dpi=180)
    plt.close(fig)


def combo_label(r):
    return f"T{r['order']}_S{r['shift']}"


def variant_color_map(rows):
    variants = sorted({r["variant"] for r in rows})
    cmap = plt.get_cmap("tab20")
    return {v: cmap(i % 20) for i, v in enumerate(variants)}


def tradeoff_scatter(ax, rows, x_key, y_key, xlabel, ylabel, title, colors):
    # group by variant so each architecture gets its own color / line
    variants = sorted({r["variant"] for r in rows})

    for v in variants:
        vrows = [r for r in rows if r["variant"] == v]
        vrows = sorted(vrows, key=lambda r: (int(r["order"]), int(r["shift"])))

        xs = [int(r[x_key]) for r in vrows]
        ys = [int(r[y_key]) for r in vrows]

        ax.plot(
            xs,
            ys,
            "-o",
            label=v,
            color=colors[v],
            linewidth=1.8,
            markersize=5,
            alpha=0.9,
        )

        # annotate each point with T/S combo
        for r, x, y in zip(vrows, xs, ys):
            ax.annotate(
                combo_label(r),
                (x, y),
                fontsize=7,
                xytext=(4, 3),
                textcoords="offset points",
                color=colors[v],
                alpha=0.9,
            )

    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.grid(True, alpha=0.25)


def plot_architecture_tradeoffs(rows, out_dir):
    """
    4 clear architecture trade-off plots across all (T,S) combinations:
      - PEs vs latency
      - LUT words vs latency
      - PEs vs instruction count
      - LUT words vs instruction count
    """
    colors = variant_color_map(rows)

    fig, axs = plt.subplots(2, 2, figsize=(15, 11))
    axs = axs.ravel()

    tradeoff_scatter(
        axs[0],
        rows,
        "total_latency_cc",
        "active_pes",
        "Latency (clock cycles)",
        "Active PEs",
        "Architectures — Resources vs Latency",
        colors,
    )

    tradeoff_scatter(
        axs[1],
        rows,
        "total_latency_cc",
        "lut_words",
        "Latency (clock cycles)",
        "LUT words (SRAM memory)",
        "Architectures — Memory vs Latency",
        colors,
    )

    tradeoff_scatter(
        axs[2],
        rows,
        "n_instructions",
        "active_pes",
        "Instruction count",
        "Active PEs",
        "Architectures — Resources vs Instruction count",
        colors,
    )

    tradeoff_scatter(
        axs[3],
        rows,
        "n_instructions",
        "lut_words",
        "Instruction count",
        "LUT words (SRAM memory)",
        "Architectures — Memory vs Instruction count",
        colors,
    )

    # one clean shared legend
    handles = [
        Line2D(
            [0], [0], color=colors[v], marker="o", linewidth=2, markersize=6, label=v
        )
        for v in sorted(colors)
    ]
    fig.legend(
        handles=handles,
        loc="lower center",
        ncol=min(5, len(handles)),
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, -0.01),
    )

    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(os.path.join(out_dir, f"architecture_tradeoffs.png"), dpi=180)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(
        description="Clear Pareto plots for the CGRA sine summary."
    )
    p.add_argument("--input", default="pareto_out/summary.csv")
    p.add_argument("--out", default="plots")
    p.add_argument("--architecture", default="False")
    p.add_argument("--variant", type=str, nargs="*", default=["DUAL", "QUAD", "HYBRID", "PIPE3", "DERIV1"])
    p.add_argument("--order", type=int, default=None)

    args = p.parse_args()

    if not args.architecture:
        all_rows = load_rows(args.input)
        if args.order is not None:
            rows = [r for r in all_rows if r.get("order") == args.order]
        else:
            rows = all_rows
    else:
        all_rows = load_rows(args.input)
        if args.order is not None:
            rows = [r for r in all_rows if r.get("variant") in args.variant and (args.order is None or r.get("order") == args.order) and (r.get("order") == args.order)]
        else:
            rows = [r for r in all_rows if r.get("variant") in args.variant and (args.order is None or r.get("order") == args.order)]

    ensure_dir(args.out)
    plot_pipeline(rows, args.out)
    plot_memory(rows, args.out)
    plot_throughput(rows, args.out)
    plot_shift_sweeps(rows, args.out)
    plot_architecture_comparisons(rows, args.out)
    plot_architecture_overview(rows, args.out)
    plot_architecture_tradeoffs(rows, args.out)
    print(f"Wrote plots to {args.out}")


if __name__ == "__main__":
    main()
