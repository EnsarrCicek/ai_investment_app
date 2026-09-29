"""POSITION-EXIT-1 yerel CLI (ağsız; yalnızca yerel JSON okur/yazar).

Kullanım: python -m app.research.position_exit <senaryolar.json> [--out <çıktı.json>]

Girdi: {"label": ..., "scenarios": [{"name", "data_origin": "TEMSILI"|"GERCEK", "entry", "params",
        "bars", "runs": [{"policy", "executions": [...]}], "position_review_payload"?}]}
GERCEK girdide `position_review_payload` zorunludur ve mevcut position_review sonucu
DEGERLENDI değilse simülasyon ÇALIŞTIRILMAZ (engel aşılmaz).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.research.position_exit.engine import ScenarioError, simulate
from app.services.portfolio.position_review import VALUED, review

COLUMNS = ("policy", "sold_quantity", "remaining_quantity", "remaining_cost", "cumulative_net_sale_proceeds",
           "principal_recovered", "realized_pnl", "unrealized_pnl_before_exit_fees", "open_request", "fee_basis")


def guard_real_input(scenario: dict) -> str | None:
    if scenario.get("data_origin") == "TEMSILI":
        return None
    if scenario.get("data_origin") != "GERCEK":
        return "DATA_ORIGIN_BELIRSIZ"
    payload = scenario.get("position_review_payload")
    if not payload:
        return "POSITION_REVIEW_GIRDISI_YOK"
    rows = [r for r in review(payload)["positions"] if r["symbol"] == str(scenario.get("symbol", "")).upper()]
    if len(rows) != 1:
        return "POSITION_REVIEW_SEMBOL_YOK"
    return None if rows[0]["status"] == VALUED else f"POSITION_REVIEW_ENGELI:{rows[0]['status']}"


def run_file(data: dict) -> dict:
    out = {"label": data.get("label"), "scenarios": []}
    for sc in data["scenarios"]:
        blocked = guard_real_input(sc)
        entry = {"name": sc["name"], "data_origin": sc.get("data_origin"), "blocked": blocked, "runs": []}
        if blocked is None:
            for run in sc["runs"]:
                try:
                    result = simulate(sc, run["policy"], run.get("executions", []))
                    result.pop("_exact")
                except ScenarioError as exc:
                    result = {"policy": run["policy"], "error": str(exc)}
                entry["runs"].append(result)
        out["scenarios"].append(entry)
    return out


def table(result: dict) -> str:
    lines = []
    for sc in result["scenarios"]:
        lines.append(f"\n## {sc['name']} ({sc['data_origin']})" + (f" — ENGELLENDI: {sc['blocked']}" if sc["blocked"] else ""))
        lines.append("| " + " | ".join(COLUMNS) + " |")
        lines.append("|" + "---|" * len(COLUMNS))
        for run in sc["runs"]:
            if "error" in run:
                lines.append(f"| {run['policy']} | HATA: {run['error']} |")
                continue
            s = run["summary"] | {"policy": run["policy"]}
            lines.append("| " + " | ".join(str(s[c]) for c in COLUMNS) + " |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 3) or (len(argv) == 3 and argv[1] != "--out"):
        print(__doc__.split("Girdi:")[0].strip(), file=sys.stderr)
        return 2
    data = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    result = run_file(data)
    if len(argv) == 3:
        Path(argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"# {result['label']}")
    print(table(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
