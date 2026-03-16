# 晨间 Brief 管线

## 给 Agent 的说明

每天早上7点自动生成并发送晨间 Brief，汇报：
- **💡 主动帮做的事**：基于录音/对话主动查询或准备的信息（机票、挂号、路线等）
- **🔴 重要结论**：需要用户关注的关键信息
- **🎯 需要你选**：需要用户决策的 A/B 选项
- **🔵 跟进**：次要更新和进度
- **📊 系统状态**：一行系统概况

**最低依赖**：只需 `chat` 数据源（自动可用）。
**增强效果**：配置 `audio` 后可引用用户原话；配置 `stock` 后汇报行情。

## 配置方式

在 `config.yaml` 中设置（通常用默认值即可）：

```yaml
pipelines:
  daily-brief:
    enabled: true
    send_to_feishu: true
    dry_run: false    # true = 测试模式，不调用 LLM
```

## 定时任务

```bash
# 查看当前定时任务
crontab -l | grep daily_brief

# 手动生成今天的 Brief（用于测试）
python3 src/services/generators/daily_brief.py --date 2026-03-16 --format
```

## 验证

```bash
python3 main.py plugins verify daily-brief
python3 main.py plugins info daily-brief
```

## 输出示例

```
☀️ 早安 Brief | 3月16日

**💡 帮你做了这些**

**查了北京→福州机票**
你上周提到想清明去福州。查了携程，清明4/4厦航¥500最便宜，3小时直飞。要帮你锁吗？

**🔴 重要**

- 300750今日放量上涨3.2%，MACD金叉信号

📊 系统状态：一切正常
```

## 相关命令

```bash
# 手动触发（生产模式）
python3 src/services/generators/daily_brief.py --date 2026-03-16 --save

# 干运行（不调用 LLM，测试数据加载）
python3 src/services/generators/daily_brief.py --date 2026-03-16 --dry-run
```
