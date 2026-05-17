from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capital_algo.broker.simulated import SimulatedTrade


def trade_to_dict(trade: SimulatedTrade) -> dict[str, Any]:
    return asdict(trade)


def metrics_from_trades(starting_balance: float, ending_balance: float, trades: list[SimulatedTrade]) -> dict[str, Any]:
    pnls = [trade.pnl for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "starting_balance": starting_balance,
        "ending_balance": ending_balance,
        "net_profit": ending_balance - starting_balance,
        "total_return_pct": ((ending_balance - starting_balance) / starting_balance) * 100 if starting_balance else 0,
        "trade_count": len(trades),
        "win_rate_pct": (len(wins) / len(trades)) * 100 if trades else 0,
        "average_win": gross_profit / len(wins) if wins else 0,
        "average_loss": sum(losses) / len(losses) if losses else 0,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "best_trade": max(pnls) if pnls else 0,
        "worst_trade": min(pnls) if pnls else 0,
    }


def write_backtest_report(
    report_directory: Path,
    run_name: str,
    config_snapshot: dict[str, Any],
    metrics: dict[str, Any],
    trades: list[SimulatedTrade],
    rejected_signals: list[dict[str, Any]],
) -> Path:
    run_directory = report_directory / run_name
    run_directory.mkdir(parents=True, exist_ok=True)

    (run_directory / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "metrics": metrics,
                "config": config_snapshot,
                "rejected_signals": rejected_signals,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with (run_directory / "trades.csv").open("w", newline="", encoding="utf-8") as file:
        fieldnames = [
            "instrument",
            "action",
            "size",
            "entry_price",
            "stop_loss",
            "take_profit",
            "entry_time",
            "exit_price",
            "exit_time",
            "pnl",
            "exit_reason",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for trade in trades:
            row = trade_to_dict(trade)
            row["action"] = trade.action.value
            writer.writerow({key: row.get(key) for key in fieldnames})

    return run_directory

