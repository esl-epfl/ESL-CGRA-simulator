"""
Plot the two Pareto curves from pareto_out/summary.csv.

  Plot 1: Latency vs Active PEs  (resources)
  Plot 2: Latency vs LUT words   (memory)

Usage:
  python plot.py
  python plot.py --shift 10          # single SHIFT only
  python plot.py --input summary.csv
"""

import csv, os, argparse
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def pareto_front(xs, ys):
    """Indices of Pareto-optimal points (minimize both x and y)."""
    indexed = sorted(enumerate(zip(xs, ys)), key=lambda t: (t[1][0], t[1][1]))
    front = []
    best_y = float("inf")
    for idx, (x, y) in indexed:
        if y < best_y:
            front.append(idx)
            best_y = y
    return front


def dedup(rows):
    """Merge rows that land on the same (lat, pes, lut) point."""
    seen = {}
    for r in rows:
        key = (int(r["total_latency_cc"]), int(r["active_pes"]), int(r["lut_words"]))
        if key not in seen:
            seen[key] = dict(r)
            seen[key]["_label"] = r["variant"]
        else:
            seen[key]["_label"] += " / " + r["variant"]
    return list(seen.values())


def plot_pareto(rows, x_key, y_key, xlabel, ylabel, title, path):
    pts = dedup(rows)
    xs = [int(p[x_key]) for p in pts]
    ys = [int(p[y_key]) for p in pts]
    labels = [p["_label"] for p in pts]

    fig, ax = plt.subplots(figsize=(11, 7))
    ax.scatter(xs, ys, s=70, c="#1565C0", zorder=3)

    # Pareto front
    fi = pareto_front(xs, ys)
    if len(fi) >= 2:
        fpts = sorted([(xs[i], ys[i]) for i in fi])
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

    # Labels
    for i in range(len(xs)):
        parts = labels[i].split(" / ")
        txt = parts[0] + (f" +{len(parts)-1}" if len(parts) > 1 else "")
        ax.annotate(
            txt, (xs[i], ys[i]), fontsize=7, xytext=(6, 4), textcoords="offset points"
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
    rows = [r for r in rows if int(r["shift"]) == a.shift]
    print(f"Loaded {len(rows)} variants at SHIFT={a.shift}")

    os.makedirs("pareto_out/plots", exist_ok=True)

    plot_pareto(
        rows,
        x_key="total_latency_cc",
        y_key="active_pes",
        xlabel="Latency (clock cycles)",
        ylabel="Active PEs (resources)",
        title=f'Latency vs Resources  —  ORDER={rows[0]["order"]}, SHIFT={a.shift}',
        path="pareto_out/plots/latency_vs_resources.png",
    )

    plot_pareto(
        rows,
        x_key="total_latency_cc",
        y_key="lut_words",
        xlabel="Latency (clock cycles)",
        ylabel="LUT words (SRAM memory)",
        title=f'Latency vs Memory  —  ORDER={rows[0]["order"]}, SHIFT={a.shift}',
        path="pareto_out/plots/latency_vs_memory.png",
    )


if __name__ == "__main__":
    main()
