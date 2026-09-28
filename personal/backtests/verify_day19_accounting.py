"""验证真实 Tick 下的部分成交、反手拆分与会计输出。

只读取 run_fill_matrix.py --single --layer reverse --scenario volume_r05_d0
生成的 CSV；不修改回测文件。失败时用非零退出码保留证据。
"""

import csv
import math
import sys
from pathlib import Path


def rows(folder, name):
    with (folder / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def main(folder):
    trades = rows(folder, "trades.csv")
    audits = rows(folder, "fill_audit.csv")
    decisions = rows(folder, "fill_decisions.csv")
    funds = rows(folder, "funds.csv")
    positions = rows(folder, "positions.csv")
    assert [(row["direct"], row["action"], float(row["qty"])) for row in trades] == [
        ("LONG", "OPEN", 3.0),
        ("LONG", "CLOSE", 3.0),
        ("SHORT", "OPEN", 1.0),
        ("SHORT", "OPEN", 4.0),
    ]
    assert [float(row["signed_qty"]) for row in audits] == [3.0, -4.0, -4.0]
    assert [float(row["actual_after"]) for row in audits] == [3.0, -1.0, -5.0]
    assert [int(row["event_seq"]) for row in audits] == [2, 3, 4]
    assert decisions[0]["status"] == "WaitingLatency"
    assert any(row["status"] == "NoLiquidity" and row["event_seq"] == "3"
               for row in decisions)
    # 一次模拟 Fill 可以先平后开生成两笔交易；两种日志的绝对数量仍一致。
    assert math.isclose(sum(float(row["qty"]) for row in trades),
                        sum(abs(float(row["signed_qty"])) for row in audits))
    total_fee = sum(float(row["fee"]) for row in trades)
    assert math.isclose(total_fee, float(funds[-1]["fee"]), abs_tol=0.02)
    assert math.isclose(float(positions[-1]["volume"]), -5.0)
    # 先平多 3 的价差收益：(5232.6 - 5231.8) × 3 × 合约乘数 300 = 720。
    assert math.isclose(float(positions[-1]["closeprofit"]), 720.0, abs_tol=0.02)
    print("Day19 会计验收通过：3 次实际成交增量、4 条开平交易、终仓 -5，"
          f"交易手续费合计 {total_fee:.2f} 与资金表一致")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：verify_day19_accounting.py 回测策略输出目录")
    main(Path(sys.argv[1]))
