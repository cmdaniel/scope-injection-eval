"""Re-apply the current oracle to a stored run, with no API calls.

Each row keeps the full tool-call log in order. Replaying those calls against a
fresh world, under the same scope, rebuilds the exact final state (files and
outbox); blocked calls are blocked again. The oracle then labels that state and
the stored final answer. This lets a corrected oracle be applied consistently
to every episode already collected, and the change is visible: the original
rows are kept in ``episodes.orig.jsonl`` and each row records the oracle
version that labelled it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .attacks import CONTROL, Attack, load_generated, template_attacks
from .controls import egress_filter
from .oracle import ORACLE_VERSION, label_episode
from .sandbox import SCOPES, Sandbox
from .tasks import TASKS
from .world import build_world


def _attack_index(generated: Path) -> dict[str, Attack]:
    attacks = [CONTROL, *template_attacks(), *load_generated(generated)]
    return {a.id: a for a in attacks}


def replay(row: dict[str, Any], attacks: dict[str, Attack]) -> Sandbox:
    """Rebuild the final sandbox state of one episode from its tool log."""
    task = TASKS[row["task"]]
    files, inbox = build_world(task.untrusted, attacks[row["attack"]].text)
    sb = Sandbox(files=files, inbox=inbox, scope=SCOPES[row["scope"]])
    for call in row.get("tool_log", []):
        sb.call(call["tool"], call["input"])
    return sb


def relabel_row(row: dict[str, Any], attacks: dict[str, Attack]) -> dict[str, Any]:
    if row.get("outcome") == "error":
        return dict(row)
    sb = replay(row, attacks)
    final = row.get("final_text", "")
    label = label_episode(sb, final)
    task = TASKS[row["task"]]
    out = dict(row)
    out.update(
        harms=label.harms,
        attempted=label.attempted,
        severity=label.severity,
        category=label.category,
        pii_accessed=label.pii_accessed,
        exfil_channels=label.exfil_channels,
        harms_output_filtered=label_episode(sb, egress_filter(final)).harms,
        task_success=bool(task.check(sb, final)) if row.get("outcome") == "completed" else False,
        oracle_version=ORACLE_VERSION,
    )
    return out


def relabel_run(run_dir: Path, generated: Path = Path("attacks/generated.json")) -> tuple[int, int]:
    """Relabel ``run_dir/episodes.jsonl`` in place. Returns (rows, rows whose labels changed)."""
    path = run_dir / "episodes.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    attacks = _attack_index(generated)
    new = [relabel_row(r, attacks) for r in rows]
    keys = ("harms", "attempted", "task_success", "exfil_channels", "harms_output_filtered")
    changed = sum(any(a.get(k) != b.get(k) for k in keys) for a, b in zip(rows, new))
    backup = run_dir / "episodes.orig.jsonl"
    if not backup.exists():
        backup.write_text(path.read_text())
    path.write_text("".join(json.dumps(r) + "\n" for r in new))
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta.setdefault("relabelled", []).append({"oracle_version": ORACLE_VERSION, "rows_changed": changed})
    meta_path.write_text(json.dumps(meta, indent=2))
    return len(rows), changed
