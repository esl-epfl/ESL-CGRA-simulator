import argparse
import csv
import os
import shutil
import subprocess
from pathlib import Path


def load_summary(summary_path: Path):
    with summary_path.open() as f:
        return list(csv.DictReader(f))


def safe_rmtree(path: Path):
    if path.exists():
        shutil.rmtree(path)


def ensure_clean_dir(path: Path):
    safe_rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def run_cmd(cmd, cwd=None):
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def write_kernel_files(kernel_dir: Path, instr_src: Path, mem_src: Path, tag: str):
    """
    Create the exact filenames expected by cgra.run():
      instructions.csv
      memory.csv
    and also keep tagged copies for traceability.
    """
    kernel_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(instr_src, kernel_dir / "instructions.csv")
    shutil.copy2(mem_src, kernel_dir / "memory.csv")
    shutil.copy2(instr_src, kernel_dir / f"instructions_{tag}.csv")
    shutil.copy2(mem_src, kernel_dir / f"memory_{tag}.csv")


def write_runner_script(dst: Path, load_addrs, store_addrs, tag: str, limit: int):
    code = f'''import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.append(str((THIS_DIR / "../../src").resolve()))
from cgra import *

KERNEL = "."

load_addrs = {load_addrs}
store_addrs = {store_addrs}

run(
    KERNEL,
    pr=["ROUT", "OPS", "R0", "R1", "ALL_LAT_INFO", "ALL_PWR_EN_INFO"],
    load_addrs=load_addrs,
    store_addrs=store_addrs,
    limit={limit},
)
'''
    dst.write_text(code)

def write_convert_script(dst: Path):
    code = '''import csv
from pathlib import Path


def convert(src, dst):
    src = Path(src)
    dst = Path(dst)
    with src.open() as f_in, dst.open("w", newline="") as f_out:
        r = csv.reader(f_in)
        w = csv.writer(f_out)
        for row in r:
            if not row:
                continue
            w.writerow(row)


if __name__ == "__main__":
    convert("memory.csv", "in.csv")
    convert("memory_out.csv", "out.csv")
'''
    dst.write_text(code)


def convert_memory_files(run_dir: Path):
    # Minimal wrapper matching the user's requested in.csv / out.csv names.
    # If a project-local convert_memory.py exists, prefer that.
    local_converter = run_dir / "convert_memory.py"
    if local_converter.exists():
        run_cmd(["python", "convert_memory.py"], cwd=str(run_dir))
    else:
        write_convert_script(run_dir / "convert_memory.py")
        run_cmd(["python", "convert_memory.py"], cwd=str(run_dir))


def maybe_copy(src: Path, dst: Path):
    if src.exists():
        shutil.copy2(src, dst)


def write_readme(dst: Path, tag: str, row: dict):
    text = (
        f"Variant: {tag}\n"
        f"Architecture: {row.get('variant','')}\n"
        f"Order: {row.get('order','')}\n"
        f"Shift: {row.get('shift','')}\n"
        f"Latency (cc): {row.get('total_latency_cc','')}\n"
        f"Active PEs: {row.get('active_pes','')}\n"
        f"LUT words: {row.get('lut_words','')}\n"
        f"Throughput factor: {row.get('throughput_factor','')}\n"
    )
    dst.write_text(text)


def default_load_store(row):
    variant = row.get("variant", "")
    tf = int(row.get("throughput_factor") or 1)
    if variant == "DUAL" or tf == 2:
        return [0, 8, 0, 0], [10000, 10004, 0, 0]
    if variant == "QUAD" or tf == 4:
        return [0, 8, 16, 24], [10000, 10004, 10008, 10012]
    return [0, 4, 0, 0], [10000, 0, 0, 0]


def generate_variants(generate_py: Path, order, shift, x_test=None):
    cmd = ["python", str(generate_py), "--order", str(order), "--shifts", str(shift)]
    if x_test is not None:
        cmd += ["--x_test", str(x_test)]
    run_cmd(cmd)


def package_variant(project_root: Path, kernel_dir: Path, rtl_root: Path, row: dict, limit: int):
    tag = row["tag"]
    src_dir = project_root / "pareto_out" / tag
    if not src_dir.exists():
        print(f"! missing generated directory for {tag}, skipping")
        return

    out_dir = rtl_root / tag
    ensure_clean_dir(out_dir)

    # keep originals
    maybe_copy(src_dir / "instructions.csv", out_dir / "instructions_original.csv")
    maybe_copy(src_dir / "memory.csv", out_dir / "memory_original.csv")
    maybe_copy(src_dir / "metrics.json", out_dir / "metrics.json")
    write_readme(out_dir / "README.txt", tag, row)

    # prepare kernel workspace exactly as cgra.run expects
    ensure_clean_dir(kernel_dir)
    write_kernel_files(kernel_dir, src_dir / "instructions.csv", src_dir / "memory.csv", tag)

    load_addrs, store_addrs = default_load_store(row)
    write_runner_script(out_dir / "run_kernel.py", load_addrs, store_addrs, tag, limit)
    
    # also keep a copy inside the kernel workspace for reproducibility
    maybe_copy(out_dir / "run_kernel.py", kernel_dir / "run_kernel.py")

    # execute the simulation from project root so ../src works from kernel_dir
    run_cmd(["python", "run_kernel.py"], cwd=str(kernel_dir))

    # collect outputs
    maybe_copy(kernel_dir / "instructions.csv", out_dir / "instructions.csv")
    maybe_copy(kernel_dir / "memory.csv", out_dir / "memory.csv")
    maybe_copy(kernel_dir / "memory_out.csv", out_dir / "memory_out.csv")

    # convert to in.csv / out.csv in the packaged folder
    if (out_dir / "memory.csv").exists() and (out_dir / "memory_out.csv").exists():
        convert_memory_files(out_dir)


def main():
    p = argparse.ArgumentParser(description="Generate all CGRA variants and package RTL sim artifacts per variant.")
    p.add_argument("--project-root", default=".")
    p.add_argument("--generate", default="generate.py")
    p.add_argument("--kernel", default="sine_approx")
    p.add_argument("--rtl-dir", default="rtl_simulation")
    p.add_argument("--order", type=int, nargs="+", required=True)
    p.add_argument("--shift", type=int, nargs="+", required=True)
    p.add_argument("--x-tests", type=float, nargs="*", default=None,
                   help="Optional x_test values. If omitted, uses generate.py default.")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--keep-pareto", action="store_true")
    args = p.parse_args()

    project_root = Path(args.project_root).resolve()
    generate_py = (project_root / args.generate).resolve()
    kernel_dir = (project_root / args.kernel).resolve()
    rtl_root = (project_root / args.rtl_dir).resolve()

    rtl_root.mkdir(parents=True, exist_ok=True)
    if not args.keep_pareto:
        safe_rmtree(project_root / "pareto_out")

    x_tests = args.x_tests if args.x_tests else [None]

    for _order in args.order:
        for _shift in args.shift:
            for x_test in x_tests:
                generate_variants(generate_py, _order, _shift, x_test)
                summary_path = project_root / "pareto_out" / "summary.csv"
                if not summary_path.exists():
                    raise FileNotFoundError(f"Expected summary at {summary_path}")
                rows = load_summary(summary_path)
                rows = [r for r in rows if int(r["order"]) == _order and int(r["shift"]) == _shift]
                if not rows:
                    print(f"! no rows found for O={_order}, S={_shift}")
                    continue
                for row in rows:
                    package_variant(project_root, kernel_dir, rtl_root, row, args.limit)

    print(f"\nDone. Packaged simulations are in: {rtl_root}")


if __name__ == "__main__":
    main()
