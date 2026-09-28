"""验证“部分成交后把目标改为实际仓位”能取消未成交剩余量。"""

import csv
import sys
from pathlib import Path


def read_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main(folder):
    signals = read_rows(folder / "signals.csv")
    trades = read_rows(folder / "trades.csv")
    audits = read_rows(folder / "fill_audit.csv")
    decisions = read_rows(folder / "fill_decisions.csv")
    positions = read_rows(folder / "positions.csv")
    replacements = read_rows(folder / "target_replacements.csv")
    equity_events = read_rows(folder / "equity_events.csv")
    assert [float(row["target"]) for row in signals] == [10.0, 7.0]
    assert [float(row["qty"]) for row in trades] == [7.0]
    assert [float(row["signed_qty"]) for row in audits] == [7.0]
    assert any(row["status"] == "NoChange" and row["target"] == "7"
               for row in decisions)
    assert float(positions[-1]["volume"]) == 7.0
    assert len(replacements) == 1
    assert [float(replacements[0][key]) for key in
            ("old_target", "new_target", "actual_before", "old_remaining")] == [10.0, 7.0, 7.0, 3.0]
    assert float(equity_events[0]["abs_gap"]) == 10.0
    assert all(float(row["abs_gap"]) == 0.0 for row in equity_events[1:])
    print("Day20 取消剩余量验收通过：目标 10→7，仅成交 7 手，终仓 7 手")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：verify_day20_cancel.py 回测策略输出目录")
    main(Path(sys.argv[1]))
