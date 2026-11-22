"""Command-line entry point: scopeeval {run,report,detect,generate,label-export,kappa,plan}."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agents import DEFENSES, ClaudeAgent, SimulatedAgent
from .attacks import CONTROL, load_generated, template_attacks
from .experiment import grid, run_grid
from .report import write_report
from .sandbox import SCOPES
from .stats import required_n
from .tasks import TASKS

GENERATED = Path("attacks/generated.json")

# Rough planning numbers, not a quote: ~12k input and ~1.5k output tokens per episode.
PRICES = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50)}
EST_IN, EST_OUT = 12_000, 1_500


def _split(value: str, allowed: list[str]) -> list[str]:
    items = allowed if value == "all" else value.split(",")
    unknown = [i for i in items if i not in allowed]
    if unknown:
        sys.exit(f"unknown values {unknown}; choose from {allowed}")
    return items


def _attacks(which: str):
    attacks = [CONTROL]
    if which in {"templates", "all"}:
        attacks += template_attacks()
    if which in {"generated", "all"}:
        gen = load_generated(GENERATED)
        if not gen:
            sys.exit(f"no generated attacks at {GENERATED}; run `scopeeval generate` first")
        attacks += gen
    return attacks


def _cells(args):
    return grid(
        [TASKS[t] for t in _split(args.tasks, list(TASKS))],
        _attacks(args.attacks),
        _split(args.scopes, list(SCOPES)),
        _split(args.defenses, list(DEFENSES)),
        args.repeats,
    )


def _estimate(n: int, model: str) -> str:
    if model not in PRICES:
        return "no price on file for this model"
    pin, pout = PRICES[model]
    cost = n * (EST_IN * pin + EST_OUT * pout) / 1e6
    return f"~${cost:,.2f} (assumes ~{EST_IN // 1000}k input / ~{EST_OUT / 1000:.1f}k output tokens per episode)"


def _client():
    import anthropic

    return anthropic.Anthropic()


def cmd_plan(args) -> None:
    cells = _cells(args)
    print(f"episodes: {len(cells)}")
    print(f"estimated cost on {args.model}: {_estimate(len(cells), args.model)}")
    print(f"episodes per cell for a +/-7 point CI at p=0.3: {required_n(0.3, 0.07)}")


def cmd_run(args) -> None:
    cells = _cells(args)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out or f"results/{args.agent}-{stamp}")
    meta = {"agent": args.agent, "tasks": args.tasks, "attacks": args.attacks, "scopes": args.scopes,
            "defenses": args.defenses, "repeats": args.repeats, "started": stamp}
    if args.agent == "simulated":
        meta.update(compliance=args.compliance, seed=args.seed)
        sim = SimulatedAgent(args.compliance, args.seed)
        factory = lambda defense: sim  # noqa: E731
    else:
        print(f"{len(cells)} episodes, estimated {_estimate(len(cells), args.model)}")
        if not args.yes and input("Proceed with paid API calls? [y/N] ").strip().lower() != "y":
            sys.exit("aborted")
        meta.update(model=args.model, effort=args.effort)
        client = _client()
        factory = lambda defense: ClaudeAgent(client, args.model, args.effort, defense)  # noqa: E731
    run_grid(factory, cells, out, meta)
    print(f"report: {write_report(out)}")


def cmd_report(args) -> None:
    print(write_report(Path(args.run_dir)))


def cmd_detect(args) -> None:
    from .detectors import ClaudeDetector, HeuristicDetector, evaluate

    detector = HeuristicDetector() if args.detector == "heuristic" else ClaudeDetector(_client(), args.model)
    attacks = template_attacks() + load_generated(GENERATED)
    print(json.dumps(evaluate(detector, attacks), indent=2))


def cmd_generate(args) -> None:
    from .generate import generate

    rows = generate(_client(), args.model, args.per_goal, GENERATED)
    print(f"wrote {len(rows)} rows to {GENERATED}")


def cmd_label_export(args) -> None:
    from .labels import export_sample

    print(export_sample(Path(args.run_dir), args.n, args.seed, Path(args.out)))


def cmd_kappa(args) -> None:
    from .labels import kappa_report

    print(kappa_report([Path(p) for p in args.rater_csv], Path(args.run_dir) if args.run_dir else None))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="scopeeval", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def grid_args(sp):
        sp.add_argument("--tasks", default="all")
        sp.add_argument("--attacks", choices=["templates", "generated", "all"], default="templates")
        sp.add_argument("--scopes", default="all")
        sp.add_argument("--defenses", default="none")
        sp.add_argument("--repeats", type=int, default=1)
        sp.add_argument("--model", default="claude-opus-5-5")

    sp = sub.add_parser("plan", help="count episodes and estimate cost; no API calls")
    grid_args(sp)
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("run", help="run the experiment grid")
    grid_args(sp)
    sp.add_argument("--agent", choices=["claude", "simulated"], default="simulated")
    sp.add_argument("--effort", default="medium")
    sp.add_argument("--compliance", type=float, default=0.5, help="simulated agent only")
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--out")
    sp.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("report", help="rebuild report.md for a run")
    sp.add_argument("run_dir")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("detect", help="detector AUC on template vs generated attacks")
    sp.add_argument("--detector", choices=["heuristic", "claude"], default="heuristic")
    sp.add_argument("--model", default="claude-opus-5-5")
    sp.set_defaults(func=cmd_detect)

    sp = sub.add_parser("generate", help="generate the held-out attack set (paid API calls)")
    sp.add_argument("--model", default="claude-opus-5-5")
    sp.add_argument("--per-goal", type=int, default=10)
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser("label-export", help="export a blinded sample for human raters")
    sp.add_argument("run_dir")
    sp.add_argument("--n", type=int, default=40)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--out", default="labels.csv")
    sp.set_defaults(func=cmd_label_export)

    sp = sub.add_parser("kappa", help="Cohen's kappa between raters (and the oracle)")
    sp.add_argument("rater_csv", nargs="+")
    sp.add_argument("--run-dir")
    sp.set_defaults(func=cmd_kappa)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
