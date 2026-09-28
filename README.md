# wtpy CTA 回测接口实验

> 这是基于 [wtpy 原版](https://github.com/wondertrader/wtpy) 的个人二次开发仓库，**不是 wtpy 官方项目**。原版 Python 子框架和绝大多数源码由原项目作者贡献；我的修改集中在 CTA 回测成交模型的 Python 配置入口与实验脚本。配套的 C++ 改动见 [wondertrader-cta-fill-lab](https://github.com/newbigdeng/wondertrader-cta-fill-lab)。许可见 [LICENSE](LICENSE)。

## 原版框架与架构

wtpy 是 [WonderTrader 原版](https://github.com/wondertrader/wondertrader) 的 Python 子框架。原版已提供策略基类与上下文、回测/交易/数据引擎入口、C++ 动态库接口，以及分析、优化和监控等应用组件。这些不是本仓库新增的功能。

从源码看，CTA 回测的 Python 到 C++ 路径是：

```text
Python CTA 策略与 CtaContext
  → WtBtEngine（配置与运行回测）
  → wrapper/WtBtWrapper（调用 C++ 动态库）
  → WonderTrader 的 WtBtPorter / WtBtCore
```

其他原版模块中，`WtEngine.py` 提供交易引擎入口，`WtDtEngine.py` 提供数据引擎入口，`apps/` 包含分析与优化等工具，`monitor/` 包含监控组件。这里介绍的是原版分工，不是我的开发成果。

## 我的二次开发：先简述

**我没有重写 wtpy；我为 C++ 侧新增的 CTA 回测成交模型补上 Python 配置入口，并用脚本验证不同成交假设下的回测输出。**

- 在 [`WtBtEngine.py`](wtpy/WtBtEngine.py) 的 `set_cta_strategy` 增加 `fill_model`、`event_delay` 和 `participation_rate` 参数；默认仍走原版 Legacy 行为。
- 在 [`WtBtWrapper.py`](wtpy/wrapper/WtBtWrapper.py) 对接 C++ 新入口并校验参数；可用 `WTPY_BT_PORTER_LIB` 显式指定新编译的 `WtBtPorter.so`，不必覆盖 wtpy 自带库。
- 在 [`personal/`](personal/) 放置真实 Tick 成交量检查、反手与目标覆盖验收、成交模型敏感性实验脚本。相关 C++ 成交决策、记账与单元测试在配套的 [WonderTrader 仓库](https://github.com/newbigdeng/wondertrader-cta-fill-lab)。

新模型需要与本仓库接口匹配的 C++ `WtBtPorter.so`；只安装原版 wtpy 或只替换 Python 文件，不能独立运行这些新模型。当前实验聚焦 CTA 回测，不把结果解释为真实市场成交或长期收益。

## 原版与归属

- 原版 Python 子框架：[wondertrader/wtpy](https://github.com/wondertrader/wtpy)
- 原版 C++ 框架：[wondertrader/wondertrader](https://github.com/wondertrader/wondertrader)
- 本仓库保留上游许可和 Git 历史；上面列出的二次开发内容才是我在本项目中的工作。
