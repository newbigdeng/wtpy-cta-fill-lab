"""只读审计 WT 原始 .dsb Tick 的成交量字段，不修改行情文件。"""

import argparse
import hashlib
from pathlib import Path

import numpy as np
from wtpy.wrapper.WtDtHelper import WtDataHelper


FIELDS = (
    "trading_date", "action_date", "action_time", "price",
    "total_volume", "volume", "bid_price_0", "ask_price_0",
    "bid_qty_0", "ask_qty_0",
)


def describe(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    ticks = WtDataHelper().read_dsb_ticks(str(path))
    if ticks is None or len(ticks) == 0:
        raise RuntimeError(f"无法读取 Tick：{path}")
    data = ticks.ndarray
    print(f"FILE {path}")
    print(f"SHA256 {digest}")
    print(f"ROWS {len(data)} DTYPE {data.dtype.names}")
    print("FIELDS", ",".join(FIELDS))
    for i in sorted(set(list(range(min(5, len(data)))) + list(range(max(0, len(data)-5), len(data))))):
        print("ROW", i, ",".join(str(data[name][i]) for name in FIELDS))

    # 只比较同一交易日相邻两笔，不能把跨日累计量重置误判为异常。
    dates = np.unique(data["trading_date"])
    for date in dates:
        rows = data[data["trading_date"] == date]
        total = rows["total_volume"]
        volume = rows["volume"]
        delta = np.diff(total)
        observed = volume[1:]
        finite = np.isfinite(total).all() and np.isfinite(volume).all()
        equal = np.isclose(observed, delta, rtol=0, atol=1e-8)
        first_bad = np.flatnonzero(~equal)
        print(
            "DAY", int(date), "rows", len(rows), "finite", bool(finite),
            "volume_negative", int(np.count_nonzero(volume < 0)),
            "total_decrease", int(np.count_nonzero(delta < -1e-8)),
            "delta_mismatch", len(first_bad),
            "volume_zero", int(np.count_nonzero(volume == 0)),
            "sum_volume", float(volume.sum()),
            "first_total", float(total[0]), "last_total", float(total[-1]),
        )
        # 连续 100 笔、每日首尾与异常样本都有可复核证据。
        subset = min(100, len(rows)-1)
        print("FIRST_100_MISMATCH", int(np.count_nonzero(~equal[:subset])), "OF", subset)
        for j in first_bad[:5]:
            print("MISMATCH", int(date), int(j + 1),
                  "volume", float(observed[j]), "total_diff", float(delta[j]))
        print("BOUNDARY", int(date),
              "first_volume", float(volume[0]), "last_volume", float(volume[-1]),
              "first_time", int(rows["action_time"][0]),
              "last_time", int(rows["action_time"][-1]))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.files:
        if not path.is_file():
            raise FileNotFoundError(path)
        describe(path.resolve())


if __name__ == "__main__":
    main()
