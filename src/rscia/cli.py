"""Command line interface: `rscia <command>`."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from .config import load_config


def _cfg(args):
    cfg = load_config(args.root)
    for w in cfg.warnings:
        logging.getLogger("rscia").warning(w)
    return cfg


def cmd_build_grid(args):
    from .pipeline import make_grid
    make_grid(_cfg(args))


def cmd_check(args):
    from .check import check_inputs
    df = check_inputs(_cfg(args))
    with pd.option_context("display.max_rows", None, "display.width", 200, "display.max_colwidth", 80):
        print(df.to_string(index=False))
    print(f"\n{int(df.exists.sum())} of {len(df)} inputs present.")


def cmd_prepare(args):
    from .pipeline import prepare_pressures
    prepare_pressures(_cfg(args))


def _find_run(cfg, run_id):
    from .pipeline import expand_runs
    runs = {r.run_id: r for r in expand_runs(cfg)}
    if run_id not in runs:
        sys.exit(f"Unknown run '{run_id}'. Available: {', '.join(runs)}")
    return runs[run_id]


def cmd_run(args):
    from .pipeline import run_scenario
    cfg = _cfg(args)
    run_scenario(cfg, _find_run(cfg, args.scenario))


def cmd_run_all(args):
    from .pipeline import expand_runs, load_grid, run_scenario
    from .reporting import compare
    cfg = _cfg(args)
    grid = load_grid(cfg)
    runs = expand_runs(cfg)
    for r in runs:
        run_scenario(cfg, r, grid)
    base = runs[0].run_id
    rows = [compare(cfg, grid, r.run_id, base) for r in runs[1:]]
    if rows:
        tab = pd.concat(rows, ignore_index=True)
        tab.to_csv(cfg.outputs_dir / "comparisons" / "all_runs_summary.csv", index=False)
        print(tab[["run", "total_baseline", "total_scenario", "change_pct"]].to_string(index=False))


def cmd_compare(args):
    from .pipeline import load_grid
    from .reporting import compare
    cfg = _cfg(args)
    print(compare(cfg, load_grid(cfg), args.scenario, args.baseline).to_string(index=False))


def cmd_validate(args):
    from .pipeline import load_grid
    from .validation import validate
    cfg = _cfg(args)
    s = validate(cfg, load_grid(cfg), args.scenario)
    print(s.to_string(index=False) if not s.empty else "No metrics to validate.")


def cmd_maps(args):
    from .pipeline import expand_runs, load_grid
    from .plots import quicklook_maps
    cfg = _cfg(args)
    quicklook_maps(cfg, load_grid(cfg), [r.run_id for r in expand_runs(cfg)])


def cmd_demo(args):
    from . import demo
    from .pipeline import expand_runs, make_grid, prepare_pressures, run_scenario
    from .plots import quicklook_maps
    from .reporting import compare
    from .validation import validate

    repo = Path(args.root).resolve()
    out = Path(args.out).resolve()
    demo.build_demo(out, repo)
    cfg = load_config(out)
    grid = make_grid(cfg)
    demo.build_demo_components(cfg, grid)
    prepare_pressures(cfg, grid)
    runs = expand_runs(cfg)
    for r in runs:
        run_scenario(cfg, r, grid)
    demo.build_demo_surveys(cfg, grid)
    print(validate(cfg, grid, "S0_baseline").to_string(index=False))
    tab = pd.concat([compare(cfg, grid, r.run_id) for r in runs[1:]], ignore_index=True)
    tab.to_csv(cfg.outputs_dir / "comparisons" / "all_runs_summary.csv", index=False)
    print(tab[["run", "total_baseline", "total_scenario", "change_pct"]].to_string(index=False))
    quicklook_maps(cfg, grid, [r.run_id for r in runs])
    print(f"\nDemo finished. Outputs in {cfg.outputs_dir}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rscia", description="Red Sea Cumulative Impact Assessment")
    ap.add_argument("--root", default=".", help="project folder containing config/ (default: current folder)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build-grid", help="build the 1 km grid from the EEZ").set_defaults(fn=cmd_build_grid)
    sub.add_parser("check", help="list present and missing inputs").set_defaults(fn=cmd_check)
    sub.add_parser("prepare", help="build baseline pressure and climate layers").set_defaults(fn=cmd_prepare)
    p = sub.add_parser("run", help="run one scenario run")
    p.add_argument("--scenario", default="S0_baseline")
    p.set_defaults(fn=cmd_run)
    sub.add_parser("run-all", help="run every scenario and compare with baseline").set_defaults(fn=cmd_run_all)
    p = sub.add_parser("compare", help="difference between a run and the baseline")
    p.add_argument("--scenario", required=True)
    p.add_argument("--baseline", default="S0_baseline")
    p.set_defaults(fn=cmd_compare)
    p = sub.add_parser("validate", help="validate a run against coral survey sites")
    p.add_argument("--scenario", default="S0_baseline")
    p.set_defaults(fn=cmd_validate)
    sub.add_parser("maps", help="quick-look PNG maps of all runs").set_defaults(fn=cmd_maps)
    p = sub.add_parser("demo", help="run the full pipeline on synthetic data")
    p.add_argument("--out", default="demo_run")
    p.set_defaults(fn=cmd_demo)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    logging.getLogger("rasterio").setLevel(logging.WARNING)
    logging.getLogger("fiona").setLevel(logging.WARNING)
    logging.getLogger("pyogrio").setLevel(logging.WARNING)
    args.fn(args)


if __name__ == "__main__":
    main()
