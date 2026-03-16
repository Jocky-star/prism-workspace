# A股行情数据源

## 给 Agent 的说明

当用户需要关注 A 股行情时启用此插件。
启用后，系统在交易日定期拉取自选股的实时行情和市场新闻，用于：
- **晨间 Brief**：汇报持仓相关的重要涨跌和消息
- **行情监控**：检测技术指标信号（MACD、均线突破等）

**需要**：`akshare` 库（`pip install akshare`）

## 配置方式

在 `config.yaml` 中设置：

```yaml
sources:
  stock:
    enabled: true
    watchlist:
      - "600036"   # 招商银行
      - "000001"   # 平安银行
      - "300750"   # 宁德时代
    include_news: true
    news_limit: 10
```

## 验证

```bash
python3 main.py plugins verify stock
```

## 输出格式

```json
{
  "date": "2026-03-16",
  "available": true,
  "quotes": [
    {"code": "600036", "name": "招商银行", "price": 35.6, "change_pct": 1.2}
  ],
  "news": [
    {"title": "...", "time": "2026-03-16 10:30", "source": "东方财富"}
  ],
  "signals": ["600036 MACD金叉"]
}
```

## 相关命令

```bash
# 手动拉取行情
python3 src/sources/stock/news_monitor.py

# 查看技术指标信号（需要 a-share-monitor 技能）
# 在 Agent 对话中说: 帮我看看自选股今天有没有信号

# 插件详情
python3 main.py plugins info stock
```

## 相关技能

此插件使用以下 OpenClaw Agent 技能：
- `a-share-monitor` — A股行情监控和技术指标分析
- `mootdx-china-stock-data` — 实时行情数据拉取（TDX 协议）

## 何时启用

- 用户持有 A 股仓位，希望每天收到行情简报
- 用户需要盯盘某些股票的技术信号

## 不需要时

不炒股就不用启用。Daily Brief 不依赖此插件。
