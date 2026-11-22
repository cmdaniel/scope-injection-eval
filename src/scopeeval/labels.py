"""Human labelling: export a blinded sample, then measure agreement.

Raters see the task, the injected text and the observable effects (tool calls,
sent mail, final answer), but not the oracle's label. They pick one category
from the pre-registered taxonomy. Agreement is Cohen's kappa, between raters
and between each rater and the oracle.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from .oracle import CATEGORIES
from .report import load
from .stats import cohen_kappa

ALLOWED = ("NONE",) + CATEGORIES


def export_sample(run_dir: Path, n: int, seed: int, out: Path) -> Path:
    rows = [r for r in load(run_dir / "episodes.jsonl") if r["outcome"] != "error"]
    rng = random.Random(seed)
    sample = rng.sample(rows, min(n, len(rows)))
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["episode_key", "task", "attack", "scope", "tool_calls", "outbox", "final_text", "label"])
        for r in sample:
            key = f"{r['task']}|{r['attack']}|{r['scope']}|{r['defense']}|{r['repeat']}"
            calls = json.dumps([(c["tool"], c["input"], "allowed" if c["allowed"] else "BLOCKED") for c in r["tool_log"]])
            w.writerow([key, r["task"], r["attack"], r["scope"], calls, json.dumps(r["outbox"]), r["final_text"], ""])
    return out


def _read_labels(path: Path) -> dict[str, str]:
    with path.open() as fh:
        labels = {row["episode_key"]: row["label"].strip().upper() for row in csv.DictReader(fh)}
    bad = {k: v for k, v in labels.items() if v not in ALLOWED}
    if bad:
        raise ValueError(f"{path}: labels must be one of {ALLOWED}; got {sorted(set(bad.values()))}")
    return labels


def oracle_labels(run_dir: Path) -> dict[str, str]:
    return {
        f"{r['task']}|{r['attack']}|{r['scope']}|{r['defense']}|{r['repeat']}": r["category"]
        for r in load(run_dir / "episodes.jsonl")
        if r["outcome"] != "error"
    }


def agreement(a: dict[str, str], b: dict[str, str]) -> tuple[int, float]:
    keys = sorted(set(a) & set(b))
    return len(keys), cohen_kappa([a[k] for k in keys], [b[k] for k in keys])


def kappa_report(rater_files: list[Path], run_dir: Path | None) -> str:
    raters = {p.stem: _read_labels(p) for p in rater_files}
    if run_dir is not None:
        raters["oracle"] = oracle_labels(run_dir)
    names = list(raters)
    lines = ["| Pair | n | Cohen's kappa |", "|---|---|---|"]
    for i, x in enumerate(names):
        for y in names[i + 1 :]:
            n, k = agreement(raters[x], raters[y])
            lines.append(f"| {x} vs {y} | {n} | {k:.2f} |")
    return "\n".join(lines)
