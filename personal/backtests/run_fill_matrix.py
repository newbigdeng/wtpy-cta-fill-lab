"""Day21：固定目标与闭环目标的 CTA 成交模型敏感性实验。

每组使用独立子进程和输出目录，避免 WT 全局回测状态跨组泄漏。
固定目标层只发一次 10 手目标；闭环层在实际持仓达到 10 手后发 0 手目标。
两层不能混称“信号完全相同”：闭环策略的后续信号由成交结果反馈决定。
"""

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


CODE = "CFFEX.IF.HOT"
INITIAL_CAPITAL = 1_000_000.0  # WT funds.csv 的 dynbalance 是盈亏，不含初始资金。
SCENARIOS = (
    ("legacy", "legacy_cta", 0.0, 0),
    ("touch_d0", "causal_touch", 0.0, 0),
    ("volume_r05_d0", "volume_limited", 0.05, 0),
    ("volume_r10_d0", "volume_limited", 0.10, 0),
    ("volume_r10_d1", "volume_limited", 0.10, 1),
    ("volume_r10_d3", "volume_limited", 0.10, 3),
)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def business_hash(folder):
    digest = hashlib.sha256()
    for name in ("signals.csv", "trades.csv", "closes.csv", "funds.csv",
                 "positions.csv", "fill_decisions.csv", "fill_audit.csv",
                 "equity_events.csv", "target_replacements.csv"):
        path = folder / name
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_one(args, scenario, output_base):
    # 单次回测必须从干净进程启动；策略本身不读取其他实验输出。
    from wtpy import BaseCtaStrategy, EngineType, WtBtEngine

    class TargetStrategy(BaseCtaStrategy):
        def __init__(self):
            super().__init__("day21_" + args.layer)
            self.tick_count = 0
            self.exit_sent = False

        def on_init(self, context):
            context.stra_sub_ticks(CODE)

        def on_tick(self, context, std_code, new_tick):
            if std_code != CODE:
                return
            self.tick_count += 1
            if self.tick_count == 1:
                target = 3.0 if args.layer == "reverse" else 10.0
                context.stra_set_position(CODE, target, "initial_target")
            elif args.layer == "reverse" and self.tick_count == 2:
                # Day19 专用接线用例：+3 反手到 -5，下一 Tick 的预算 4
                # 应拆成“先平 3、再开空 1”，不能直接按 -5 全额记账。
                context.stra_set_position(CODE, -5.0, "reverse_target")
            elif args.layer == "cancel" and self.tick_count == 2:
                # Day20 接线反例：前一轮已部分成交 7/10 手，这里要求保留
                # 当前实际 7 手、取消尚未成交的 3 手；不是再补满旧目标。
                context.stra_set_position(CODE, context.stra_get_position(CODE),
                                          "cancel_remaining")
            elif args.layer == "feedback" and not self.exit_sent:
                # 此时使用策略 API 看到的仓位；模型改变成交时间后，
                # 平仓信号的创建事件也可能随之改变，属于闭环效应。
                if context.stra_get_position(CODE) >= 10.0:
                    context.stra_set_position(CODE, 0.0, "exit_on_fill")
                    self.exit_sent = True

    root = Path(args.lab_root) / "records/day21/regression"
    os.chdir(root / "run")
    _, model, rate, delay = scenario
    engine = WtBtEngine(EngineType.ET_CTA, outDir=str(output_base))
    try:
        engine.init("../common/", "configbt_tick.yaml")
        # WT 当前 Tick 回放实际覆盖到当日 15:00；显式写全天结束时间，
        # 不把整日结果误标成 09:29–09:35 的六分钟实验。
        engine.configBacktest(202101040929, 202101041500)
        engine.configBTStorage(mode="bin", path="../tick_storage_container/")
        engine.commitBTConfig()
        engine.set_cta_strategy(TargetStrategy(), slippage=args.slippage,
                                isRatioSlp=False, fill_model=model,
                                event_delay=delay, participation_rate=rate)
        engine.run_backtest(bAsync=False)
    finally:
        engine.release_backtest()


def summarize(folder, layer, scenario, repetition, vol_scale):
    signals = read_csv(folder / "signals.csv")
    trades = read_csv(folder / "trades.csv")
    funds = read_csv(folder / "funds.csv")
    audits = read_csv(folder / "fill_audit.csv")
    decisions = read_csv(folder / "fill_decisions.csv")
    equity_events = read_csv(folder / "equity_events.csv")
    replacements = read_csv(folder / "target_replacements.csv")
    last_target = float(signals[-1]["target"]) if signals else 0.0
    actual = float(audits[-1]["actual_after"]) if audits else 0.0
    final_gap = abs(last_target - actual)
    # 只统计期末尚未成交量；绝不逐 Tick 累加同一目标的剩余量。
    unfilled_qty = final_gap
    fees = sum(float(row["fee"]) for row in trades)
    last_balance = float(funds[-1]["dynbalance"]) if funds else 0.0
    if equity_events and funds:
        if abs(last_balance - float(equity_events[-1]["net_pnl"])) > 0.02:
            raise AssertionError("事件权益末值与资金表日末净盈亏不一致")
    # 每条有效 Tick 两轮撮合与策略回调后取一条权益点，避免把单个日末值
    # 当作完整回撤曲线。初始权益是固定分母，窗口回撤不年化。
    equity = [INITIAL_CAPITAL] + [INITIAL_CAPITAL + float(row["net_pnl"])
                                  for row in equity_events]
    peak = equity[0]
    drawdowns = []
    for value in equity:
        peak = max(peak, value)
        drawdowns.append((peak - value) / peak)
    max_drawdown = max(drawdowns)
    # 每条有效 Tick 在两轮撮合之后只占一个观测点；这是事件等权偏差，
    # 不将同一待成交目标的每 Tick 缺口累加成“未成交总手数”。
    event_gaps = []
    for row in equity_events:
        target = float(row["target"])
        actual_at_event = float(row["actual"])
        gap = float(row["abs_gap"])
        if abs(gap - abs(target - actual_at_event)) > 1e-8:
            raise AssertionError("逐 Tick 目标与实际仓位缺口不一致")
        event_gaps.append(gap)
    mean_event_gap = sum(event_gaps) / len(event_gaps) if event_gaps else 0.0
    replaced_residual_qty = sum(float(row["old_remaining"]) for row in replacements)
    versions = 0
    previous_target = None
    for row in signals:
        current = float(row["target"])
        if previous_target is None or current != previous_target:
            versions += 1
        previous_target = current
    _, model, rate, delay = scenario
    return {
        "layer": layer, "scenario": scenario[0], "model": model,
        "rate": rate, "latency": delay, "repeat": repetition,
        "signal_count": len(signals), "target_versions": versions,
        "decision_count": len(decisions), "equity_event_count": len(equity_events),
        "target_replacement_count": len(replacements),
        "replaced_residual_qty": replaced_residual_qty,
        "mean_event_gap": mean_event_gap,
        "trade_count": len(trades),
        "fill_qty": sum(float(row["qty"]) for row in trades),
        "unfilled_qty": unfilled_qty,
        # Legacy 没有可用于同口径半价差计算的对手盘，留空而非误报为零。
        "spread_cost": (sum(float(row["spread_cost"]) for row in audits)
                        if audits and all(row["spread_cost"] for row in audits) else ""),
        "extra_slippage": sum(float(row["extra_slippage"]) for row in audits),
        "fee": fees,
        "turnover": sum(float(row["qty"]) * float(row["price"]) * vol_scale
                        for row in trades),
        "return": last_balance / INITIAL_CAPITAL,
        "max_drawdown": max_drawdown,
        "final_target_gap": final_gap,
        "business_sha256": business_hash(folder),
        "signals_sha256": file_hash(folder / "signals.csv"),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--slippage", type=int, default=1)
    parser.add_argument("--single", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--layer", choices=("frozen", "feedback", "reverse", "cancel"))
    parser.add_argument("--scenario")
    parser.add_argument("--output-base", type=Path)
    args = parser.parse_args()
    if args.repeats < 1 or args.slippage < 0:
        parser.error("repeats 必须为正数，slippage 不得为负")
    scenario_by_name = {row[0]: row for row in SCENARIOS}
    if args.single:
        if args.layer is None or args.scenario not in scenario_by_name or args.output_base is None:
            parser.error("内部单次模式参数不全")
        run_one(args, scenario_by_name[args.scenario], args.output_base)
        return

    root = args.lab_root.resolve() / "records/day21/regression"
    run_dir = root / "run"
    if not (run_dir / "configbt_tick.yaml").is_file():
        raise FileNotFoundError(run_dir / "configbt_tick.yaml")
    experiment = root / "outputs" / args.experiment
    experiment.mkdir(parents=True, exist_ok=False)
    logs = experiment / "logs"
    logs.mkdir()
    commodity = json.loads((root / "common/commodities.json").read_text(
        encoding="utf-8", errors="replace"))
    vol_scale = float(commodity["CFFEX"]["IF"]["volscale"])
    tick_file = root / "tick_storage_container/his/ticks/CFFEX/20210104/IF_HOT.dsb"
    manifest = {
        "input_tick_sha256": file_hash(tick_file),
        "config_sha256": file_hash(run_dir / "configbt_tick.yaml"),
        "runner_sha256": file_hash(Path(__file__)),
        "porter_sha256": file_hash(Path(os.environ["WTPY_BT_PORTER_LIB"])),
        "initial_capital_for_return": INITIAL_CAPITAL,
        "vol_scale": vol_scale,
        "slippage_ticks": args.slippage,
        "start": 202101040929, "end": 202101041500,
        "scenarios": SCENARIOS, "repeats": args.repeats,
    }
    (experiment / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for layer in ("frozen", "feedback"):
        for repetition in range(1, args.repeats + 1):
            # 重复轮次的起始模型轮换，避免始终固定同一模型先运行。
            for offset in range(len(SCENARIOS)):
                scenario = SCENARIOS[(offset + repetition - 1) % len(SCENARIOS)]
                case = experiment / layer / scenario[0] / f"rep_{repetition:02d}"
                case.mkdir(parents=True, exist_ok=False)
                log = logs / f"{layer}_{scenario[0]}_{repetition:02d}.log"
                command = [sys.executable, str(Path(__file__).resolve()),
                           "--lab-root", str(args.lab_root), "--experiment", args.experiment,
                           "--slippage", str(args.slippage), "--single", "--layer", layer,
                           "--scenario", scenario[0], "--output-base", str(case)]
                with log.open("w", encoding="utf-8") as stream:
                    subprocess.run(command, check=True, stdout=stream,
                                   stderr=subprocess.STDOUT)
                row = summarize(case / f"day21_{layer}", layer, scenario,
                                repetition, vol_scale)
                rows.append(row)
                print(layer, scenario[0], repetition, row["business_sha256"][:12],
                      "trades", row["trade_count"], "gap", row["final_target_gap"],
                      flush=True)
    summary = experiment / "sensitivity.csv"
    with summary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for layer in ("frozen", "feedback"):
        for scenario in SCENARIOS:
            group = [row for row in rows if row["layer"] == layer
                     and row["scenario"] == scenario[0]]
            if len({row["business_sha256"] for row in group}) != 1:
                raise AssertionError(f"业务输出不确定：{layer}/{scenario[0]}")
    print("全部业务输出重复一致；汇总：", summary, flush=True)


if __name__ == "__main__":
    main()
