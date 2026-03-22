"""
CGRA Dataflow Graph Generator

Reads an instructions.csv and produces a DOT graph where each horizontal
level corresponds to one timestep. Read top→bottom to follow execution.

Usage:
  python dataflow_gen.py <folder>
  python dataflow_gen.py <folder> --format dot
  python dataflow_gen.py <folder> --format svg
"""

import csv, os, sys, re, argparse

N_ROWS = 4
N_COLS = 4
INSTR_SIZE = N_ROWS + 1


# Neighbor routing (matches cgra.py with wrapping)
def get_neighbor(r, c, direction):
    if direction == "RCL":
        return (r, (c - 1) % N_COLS)
    if direction == "RCR":
        return (r, (c + 1) % N_COLS)
    if direction == "RCT":
        return ((r - 1) % N_ROWS, c)
    if direction == "RCB":
        return ((r + 1) % N_ROWS, c)
    return None


MEM_OPS = {"LWD", "SWD", "LWI", "SWI"}
MUL_OPS = {"SMUL", "FXPMUL"}
CTRL_OPS = {"EXIT", "JUMP", "BEQ", "BNE", "BLT", "BGE"}
COND_OPS = {"BSFA", "BZFA"}
SHIFT_OPS = {"SRT", "SRA", "SLT"}
LOGIC_OPS = {"LAND", "LOR", "LXOR", "LNAND", "LNOR", "LXNOR"}


def op_color(op_name):
    if op_name in MEM_OPS:
        return "#4ECDC4"
    if op_name in MUL_OPS:
        return "#FF6B6B"
    if op_name in CTRL_OPS:
        return "#FFE66D"
    if op_name in COND_OPS:
        return "#A8E6CF"
    if op_name in SHIFT_OPS:
        return "#DDA0DD"
    if op_name in LOGIC_OPS:
        return "#87CEEB"
    if op_name == "NOP":
        return "#E0E0E0"
    return "#C5CAE9"


def parse_instructions(folder):
    filepath = os.path.join(folder, "instructions.csv")
    with open(filepath, "r") as f:
        rows = list(csv.reader(f))
    instrs = []
    i = 0
    while i < len(rows):
        if len(rows[i]) >= 1 and rows[i][0].strip().lstrip("-").isdigit():
            i += 1
            g = []
            for r in range(N_ROWS):
                if i < len(rows):
                    row_ops = [cell.strip() for cell in rows[i]]
                    while len(row_ops) < N_COLS:
                        row_ops.append("NOP")
                    g.append(row_ops[:N_COLS])
                    i += 1
                else:
                    g.append(["NOP"] * N_COLS)
            instrs.append(g)
        else:
            i += 1
    return instrs


def extract_op_name(op_str):
    return op_str.replace(",", " ").split()[0]


def extract_sources(op_str):
    """Extract neighbor routing sources from instruction operands."""
    tokens = op_str.replace(",", " ").split()
    directions = {"RCL", "RCR", "RCT", "RCB"}
    sources = []
    for t in tokens[1:]:
        t_upper = t.upper()
        if t_upper in directions:
            sources.append(t_upper)
        elif t_upper == "SELF":
            sources.append("SELF")
    return sources


def extract_branch_target(op_str):
    """If this is a branch/jump, return the target instruction number."""
    tokens = op_str.replace(",", " ").split()
    op = tokens[0].upper()
    if op in {"BEQ", "BNE", "BLT", "BGE"} and len(tokens) >= 4:
        try:
            return int(tokens[3])
        except ValueError:
            pass
    if op == "JUMP" and len(tokens) >= 3:
        try:
            return int(tokens[2])
        except ValueError:
            pass
    return None


def build_graph(instrs):
    """Build nodes and edges. Each node = one active PE at one timestep."""
    nodes = []
    edges = []

    for t, g in enumerate(instrs):
        for r in range(N_ROWS):
            for c in range(N_COLS):
                op_str = g[r][c]
                op_name = extract_op_name(op_str)
                if op_name == "NOP":
                    continue

                node_id = f"I{t}_R{r}C{c}"
                nodes.append(
                    {
                        "id": node_id,
                        "instr": t,
                        "row": r,
                        "col": c,
                        "op": op_str,
                        "op_name": op_name,
                    }
                )

                # Data-flow edges: neighbor reads pull from the most recent
                # non-NOP output of that neighbor PE (old_out semantics)
                sources = extract_sources(op_str)
                for src in sources:
                    if src == "SELF":
                        # Read own previous output
                        for prev_t in range(t - 1, -1, -1):
                            prev_op = extract_op_name(instrs[prev_t][r][c])
                            if prev_op != "NOP":
                                edges.append(
                                    {
                                        "from": f"I{prev_t}_R{r}C{c}",
                                        "to": node_id,
                                        "label": "SELF",
                                        "type": "self",
                                    }
                                )
                                break
                    else:
                        nr, nc = get_neighbor(r, c, src)
                        for prev_t in range(t - 1, -1, -1):
                            prev_op = extract_op_name(instrs[prev_t][nr][nc])
                            if prev_op != "NOP":
                                edges.append(
                                    {
                                        "from": f"I{prev_t}_R{nr}C{nc}",
                                        "to": node_id,
                                        "label": src,
                                        "type": "neighbor",
                                    }
                                )
                                break

                # Branch edges
                target = extract_branch_target(op_str)
                if target is not None:
                    # Find any active node at the target instruction
                    if target < len(instrs):
                        for rr in range(N_ROWS):
                            for cc in range(N_COLS):
                                if extract_op_name(instrs[target][rr][cc]) != "NOP":
                                    edges.append(
                                        {
                                            "from": node_id,
                                            "to": f"I{target}_R{rr}C{cc}",
                                            "label": f"br→{target}",
                                            "type": "branch",
                                        }
                                    )
                                    break
                            else:
                                continue
                            break

    return nodes, edges


def generate_dot(instrs, title="CGRA Dataflow"):
    """Generate DOT with strict horizontal timestep alignment."""
    nodes, edges = build_graph(instrs)
    node_set = {n["id"] for n in nodes}

    lines = []
    lines.append(f'digraph "{title}" {{')
    lines.append("  rankdir=TB;")
    lines.append("  splines=ortho;")
    lines.append("  nodesep=0.6;")
    lines.append("  ranksep=0.8;")
    lines.append(
        '  node [shape=box, style="filled,rounded", fontname="Courier", fontsize=9];'
    )
    lines.append('  edge [fontname="Courier", fontsize=7];')
    lines.append(f'  label="{title}";')
    lines.append('  labelloc=t; fontname="Helvetica"; fontsize=14;')
    lines.append("")

    # Invisible time-label column for alignment
    max_t = max(n["instr"] for n in nodes) if nodes else 0
    for t in range(max_t + 1):
        lines.append(
            f'  time_{t} [label="t={t}", shape=plaintext, fontsize=10, fontname="Helvetica Bold"];'
        )
    # Chain time labels vertically
    chain = " -> ".join(f"time_{t}" for t in range(max_t + 1))
    if chain:
        lines.append(f"  {chain} [style=invis];")
    lines.append("")

    # Subgraphs: one per timestep with rank=same
    for t in range(max_t + 1):
        t_nodes = [n for n in nodes if n["instr"] == t]
        lines.append(f"  {{ rank=same; time_{t};")
        for n in sorted(t_nodes, key=lambda x: (x["row"], x["col"])):
            color = op_color(n["op_name"])
            short_op = n["op"].replace('"', '\\"')
            label = f"PE({n['row']},{n['col']})\\n{short_op}"
            lines.append(f'    {n["id"]} [label="{label}", fillcolor="{color}"];')
        lines.append("  }")
        lines.append("")

    # Edges
    for e in edges:
        if e["from"] not in node_set or e["to"] not in node_set:
            continue
        if e["type"] == "branch":
            lines.append(
                f'  {e["from"]} -> {e["to"]} [label="{e["label"]}", '
                f'style=dashed, color="#E53935", penwidth=2, constraint=false];'
            )
        elif e["type"] == "self":
            lines.append(
                f'  {e["from"]} -> {e["to"]} [label="{e["label"]}", '
                f'style=dotted, color="#9E9E9E"];'
            )
        else:
            # Color by direction
            lbl = e["label"]
            if lbl in ("RCT", "RCB"):
                color = "#FF6B6B"
            elif lbl in ("RCL", "RCR"):
                color = "#4ECDC4"
            else:
                color = "#666666"
            lines.append(
                f'  {e["from"]} -> {e["to"]} [label="{lbl}", color="{color}"];'
            )

    lines.append("}")
    return "\n".join(lines)


def render_svg(dot_str, output_path):
    import subprocess

    dot_path = output_path.replace(".svg", ".dot")
    with open(dot_path, "w") as f:
        f.write(dot_str)
    result = subprocess.run(
        ["dot", "-Tsvg", dot_path, "-o", output_path], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  graphviz error: {result.stderr.strip()}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="CGRA Dataflow Graph Generator v2")
    parser.add_argument("folder", help="Folder containing instructions.csv")
    parser.add_argument("--format", choices=["dot", "svg", "both"], default="dot")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    folder = args.folder
    outdir = args.output or folder
    os.makedirs(outdir, exist_ok=True)

    print(f"Parsing {folder}/instructions.csv ...")
    instrs = parse_instructions(folder)
    print(f"  {len(instrs)} instructions")

    title = os.path.basename(folder.rstrip("/"))
    dot_str = generate_dot(instrs, title=title)

    if args.format in ("dot", "both"):
        dot_path = os.path.join(outdir, "dataflow.dot")
        with open(dot_path, "w") as f:
            f.write(dot_str)
        print(f"  Written: {dot_path}")

    if args.format in ("svg", "both"):
        svg_path = os.path.join(outdir, "dataflow.svg")
        if render_svg(dot_str, svg_path):
            print(f"  Written: {svg_path}")

    print("Done!")


if __name__ == "__main__":
    main()
