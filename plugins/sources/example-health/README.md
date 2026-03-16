# example-health 插件

这是一个完整的示例插件，演示如何为 Prism 编写数据源插件。

## 用途

- 开发和测试时提供 mock 健康数据
- 作为新插件的参考模板
- 验证插件系统是否正常工作

## 数据格式

每条记录包含：

| 字段 | 类型 | 说明 |
|------|------|------|
| date | string | 日期 YYYY-MM-DD |
| steps | number | 步数 |
| sleep_score | number | 睡眠质量 0-100 |
| heart_rate_avg | number | 日均心率 bpm |
| calories | number | 消耗卡路里 kcal |
| active_minutes | number | 活跃分钟数 |
| sleep_hours | number | 睡眠时长（小时） |
| water_ml | number | 饮水量（毫升） |

## 如何使用

```python
from prism.plugin_registry import PluginRegistry

registry = PluginRegistry()
plugin = registry.load("example-health")
plugin.setup({})

# 获取今天的数据
data = plugin.fetch("2026-03-16")
print(data)

# 获取一周数据
week_data = plugin.fetch_range("2026-03-10", "2026-03-16")
print(len(week_data), "条记录")
```

## 如何基于此模板创建真实插件

1. 复制此目录：`cp -r plugins/sources/example-health plugins/sources/my-plugin`
2. 修改 `manifest.yaml`：填入真实的插件信息和配置项
3. 修改 `plugin.py`：实现真实的 `fetch()` 方法
4. 在 `config.yaml` 中添加插件配置：
   ```yaml
   plugins:
     my-plugin:
       enabled: true
       api_token: "your-token"
   ```
5. 验证：`python3 main.py plugins verify my-plugin`

## 注意事项

- `fetch()` 方法必须返回列表，即使只有一条数据
- 每条记录建议包含 `date` 和 `source` 字段
- 同一天多次调用 `fetch()` 应返回相同数据（幂等）
- 失败时应返回空列表 `[]`，不要抛出异常
