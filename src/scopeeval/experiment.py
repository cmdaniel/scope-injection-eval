"""Run the experiment grid and write one JSON line per episode."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .attacks import Attack
from .oracle import label_episode
from .sandbox import SCOPES, Sandbox
from .tasks import Task
from .world import build_world


def grid(
    tasks: Iterable[Task], attacks: Iterable[Attack], scopes: Iterable[str], defenses: Iterable[str], repeats: int
) -> list[tuple[Task, Attack, str, str, int]]:
    return [
        (t, a, s, d, r)
        for t, a, s, d, r in itertools.product(list(tasks), list(attacks), list(scopes), list(defenses), range(repeats))
    ]


def run_episode(agent: Any, task: Task, attack: Attack, scope: str) -> dict[str, Any]:
    files, inbox = build_world(task.untrusted, attack.text)
    sb = Sandbox(files=files, inbox=inbox, scope=SCOPES[scope])
    try:
        result = agent.run(task, attack, sb)
    except Exception as exc:  # recorded, never silently dropped
        row: dict[str, Any] = {"outcome": "error", "detail": f"{type(exc).__name__}: {exc}"}
        if hasattr(agent, "usage"):
            row["usage"] = dict(agent.usage)
        return row
    label = label_episode(sb, result.final_text)
    row = {
        "outcome": result.outcome,
        "detail": result.detail,
        "turns": result.turns,
        "final_text": result.final_text,
        "task_success": bool(task.check(sb, result.final_text)) if result.outcome == "completed" else False,
        "harms": label.harms,
        "attempted": label.attempted,
        "severity": label.severity,
        "category": label.category,
        "pii_accessed": label.pii_accessed,
        "tool_log": [asdict(c) for c in sb.log],
        "outbox": sb.outbox,
        "transcript": result.transcript,
    }
    if hasattr(agent, "usage"):  # API agents only; the simulated agent spends nothing
        row["usage"] = dict(agent.usage)
    return row


def run_grid(agent_factory: Any, cells: list[tuple[Task, Attack, str, str, int]], out: Path, meta: dict[str, Any]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    path = out / "episodes.jsonl"
    done = set()
    if path.exists():  # resume an interrupted run
        for line in path.read_text().splitlines():
            row = json.loads(line)
            done.add((row["task"], row["attack"], row["scope"], row["defense"], row["repeat"]))
    with path.open("a") as fh:
        for i, (task, attack, scope, defense, rep) in enumerate(cells, 1):
            key = (task.id, attack.id, scope, defense, rep)
            if key in done:
                continue
            agent = agent_factory(defense)
            row = {
                "task": task.id,
                "attack": attack.id,
                "attack_source": attack.source,
                "goal": attack.goal,
                "scope": scope,
                "defense": defense,
                "repeat": rep,
                "needs_write": task.needs_write,
            }
            row.update(run_episode(agent, task, attack, scope))
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"[{i}/{len(cells)}] {task.id} {attack.id} {scope} {defense} -> {row['outcome']} {row.get('category', '')}")
    return path
