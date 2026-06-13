# customsR API 文档

Base URL（本地开发）：`http://127.0.0.1:8000`

交互式文档（FastAPI 自动生成）：

- Swagger UI：http://127.0.0.1:8000/docs
- ReDoc：http://127.0.0.1:8000/redoc

---

## 1. 概述

| 能力 | 说明 |
|------|------|
| **查询** | 只读本地 SQLite（`trade_records`），不访问 Comtrade |
| **同步** | 按需调用 UN Comtrade API，写入 SQLite；结果写入 `data_slices` 做缓存 |
| **导出** | 按查询条件导出 xlsx |

同步接口需要在项目根目录 `.env` 中配置：

```
COMTRADE_API_KEY=你的key
```

---

## 2. 通用枚举

### freq_code（频率）

| 值 | 含义 |
|----|------|
| `A` | 年度 |
| `M` | 月度 |

### flow_code（贸易流向）

| 值 | 含义 |
|----|------|
| `X` | 出口 |
| `M` | 进口 |

### data_slices.status（切片状态）

| 值 | 含义 |
|----|------|
| `ok` | 官网有数据，已写入 `trade_records` |
| `empty` | 官网暂无数据（负缓存，默认 7 天内不重复请求） |
| `error` | 上次同步失败（默认 1 天内不重复请求） |

### 切片（slice）维度

一次 Comtrade 请求对应一个切片：

```
(reporter_code, year, month, flow_code, freq_code)
```

- 年度：`month = 0`
- 月度：`month = 1..12`；同步时 `month = 0` 表示该年 12 个月 × 进出口

---

## 3. 健康检查

### `GET /api/health`

**响应示例**

```json
{
  "status": "ok",
  "records": 8113
}
```

---

## 4. 元数据

### `GET /api/meta/filters`

查询页筛选项，**仅反映 `trade_records` 中已有数据**。报告国 / 年份 / 月份联动；各下拉列表不受「自身当前选中值」约束（例如已选 USA 时，报告国列表仍显示所有有数据的国家）。

**Query 参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `reporter_code` | int | 可选，报告国 M49 代码 |
| `year` | int | 可选，年份 |
| `freq_code` | `A` \| `M` | 可选，默认按 `A` 过滤 |
| `month` | int | 可选，1–12；仅 `freq_code=M` 时有效 |

**响应字段**

| 字段 | 说明 |
|------|------|
| `reporters` | `[{ code, label, name_en }]` |
| `years` | 年份列表（降序） |
| `months` | `[{ value, label, period_label }]`；指定 `year` 且月度时含 `All of {year}`（value=0） |
| `flows` | `[{ code, label }]` |
| `frequencies` | `[{ code, label }]` |

**示例**

```
GET /api/meta/filters?freq_code=M&reporter_code=842&year=2024
```

---

### `GET /api/meta/sync-options`

左侧同步表单选项：国家来自 Comtrade 参考表（英文），年份 1962–当前年，月份 1–12，并附带已有 `data_slices` 摘要（`slice_hints`）。

**响应字段**

| 字段 | 说明 |
|------|------|
| `reporters` | Comtrade 全部报告国（约 252 个） |
| `years` | 1962–当前年，降序 |
| `months` | 1–12 月英文标签 |
| `frequencies` | 年度 / 月度 |
| `slice_hints` | 本地已有切片状态摘要 |

---

### `GET /api/slices/meta`

「同步缓存」页筛选项，**仅来自 `data_slices` 已有记录**。

**响应示例**

```json
{
  "reporters": [{ "code": 842, "label": "USA" }],
  "years": [2024, 2023],
  "frequencies": [{ "code": "M", "label": "月度" }],
  "statuses": [
    { "code": "ok", "label": "有数据" },
    { "code": "empty", "label": "官网暂无" },
    { "code": "error", "label": "同步失败" }
  ],
  "empty_ttl_days": 7
}
```

---

## 5. 贸易数据查询

### `GET /api/trade`

分页查询本地贸易记录。

**Query 参数**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `reporter_code` | int | — | 报告国 |
| `year` | int | — | 年份 |
| `month` | int | — | 1–12，仅月度 |
| `freq_code` | `A` \| `M` | `A` | 频率 |
| `flow_code` | `X` \| `M` | — | 流向 |
| `partner_name` | string | — | 伙伴国名称模糊匹配 |
| `partner_scope` | `countries` \| `total` | `countries` | `total` 仅 World 合计 |
| `page` | int | `1` | 页码 |
| `page_size` | int | `20` | 每页条数，最大 200 |

**说明**

- `freq_code=M` 时仅返回 `month > 0` 的记录
- `freq_code=A` 时仅返回 `month = 0` 的记录

**响应示例**

```json
{
  "items": [
    {
      "id": 1,
      "reporter_code": 842,
      "reporter_label": "USA",
      "partner_code": 156,
      "partner_name": "China",
      "freq_code": "M",
      "freq_label": "月度",
      "year": 2024,
      "month": 12,
      "month_label": "December",
      "period_label": "December 2024",
      "flow_code": "M",
      "flow_label": "进口",
      "trade_value_usd": 123456789,
      "source": "un_comtrade",
      "fetched_at": "2026-06-12T18:00:00+00:00"
    }
  ],
  "total": 430,
  "page": 1,
  "page_size": 20,
  "pages": 22
}
```

---

### `GET /api/trade/export`

按与 `/api/trade` 相同的筛选条件导出 **全部匹配记录** 为 xlsx（非仅当前页）。

**Query 参数**：与 `/api/trade` 相同（无分页参数）。

**响应**

- Content-Type: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
- 文件名：`trade_export_YYYYMMDD_HHMMSS.xlsx`

**响应头**

| Header | 说明 |
|--------|------|
| `X-Export-Total` | 匹配总条数 |
| `X-Export-Rows` | 本次导出条数 |
| `X-Export-Truncated` | `1` 表示超过上限 50000 已截断 |

**错误**

| 状态码 | 说明 |
|--------|------|
| `404` | 无数据可导出 |

---

## 6. 同步缓存查询

### `GET /api/slices`

分页查询 `data_slices`（同步任务状态 / 负缓存）。

**Query 参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| `reporter_code` | int | 报告国 |
| `year` | int | 年份 |
| `freq_code` | `A` \| `M` | 频率 |
| `status` | `ok` \| `empty` \| `error` | 切片状态 |
| `page` | int | 页码，默认 1 |
| `page_size` | int | 每页条数，最大 200 |

**响应示例**

```json
{
  "summary": { "total": 103, "ok": 73, "empty": 30, "error": 0 },
  "items": [
    {
      "reporter_code": 842,
      "reporter_label": "USA",
      "year": 2024,
      "month": 12,
      "period_label": "December 2024",
      "freq_code": "M",
      "flow_code": "M",
      "flow_label": "进口",
      "status": "ok",
      "status_label": "有数据",
      "record_count": 215,
      "fetched_at": "2026-06-12T18:00:00+00:00",
      "cache_note": "不会重复请求",
      "freshness": "fresh",
      "retryable": false
    }
  ],
  "total": 103,
  "page": 1,
  "page_size": 20,
  "pages": 6
}
```

---

## 7. 从 Comtrade 同步

### 请求体 `SyncSliceRequest`

```json
{
  "reporter_code": 156,
  "year": 2024,
  "flow_code": null,
  "freq_code": "M",
  "month": 12,
  "force_refresh": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `reporter_code` | int | 是 | UN M49 报告国代码 |
| `year` | int | 是 | 1962–当前年 |
| `flow_code` | `X` \| `M` | 否 | 省略则同步进出口各一切片 |
| `freq_code` | `A` \| `M` | 否 | 默认 `A` |
| `month` | int | 否 | 月度：`0`=全年 12 月，`1–12`=单月；年度忽略 |
| `force_refresh` | bool | 否 | `true` 跳过本地缓存，强制请求 Comtrade |

**切片数量（未省略 flow_code 时）**

| 场景 | API 请求次数 |
|------|----------------|
| 年度，单流向 | 1 |
| 年度，进出口 | 2 |
| 月度，单月，单流向 | 1 |
| 月度，单月，进出口 | 2 |
| 月度，`month=0`（全年），进出口 | 24（12 月 × 2 流向） |

相邻请求间隔约 1 秒，避免触发 Comtrade 限流。

---

### `POST /api/sync/slice`

同步完成后一次性返回 JSON。

**响应示例**

```json
{
  "status": "ok",
  "message": "同步完成，共 432 条记录",
  "record_count": 432,
  "records_upserted": 432,
  "cached": false,
  "freq_code": "M",
  "month": 12,
  "slices": [
    {
      "reporter_code": 842,
      "year": 2024,
      "month": 12,
      "flow_code": "X",
      "freq_code": "M",
      "status": "ok",
      "record_count": 215,
      "cached": false,
      "message": "已从 UN Comtrade 同步 215 条记录"
    }
  ]
}
```

**顶层 status**

| 值 | 含义 |
|----|------|
| `ok` | 至少一个切片有数据 |
| `empty` | 全部切片官网暂无 |
| `error` | 至少一个切片失败 |

**错误**

| 状态码 | 说明 |
|--------|------|
| `400` | 参数无效 / 不支持的国家或年份 |
| `500` | 未配置 `COMTRADE_API_KEY` 等 |

---

### `POST /api/sync/slice/stream`

与 `/api/sync/slice` 相同请求体，通过 **SSE** 推送进度。前端同步按钮使用此接口。

**Content-Type**: `text/event-stream`

**事件类型**

#### `start`

```json
{ "type": "start", "total": 24 }
```

#### `progress`

```json
{
  "type": "progress",
  "current": 3,
  "total": 24,
  "percent": 13,
  "label": "December 2024 · 进口",
  "slice": { "...": "单切片 SyncSliceResult 字段" }
}
```

#### `done`

```json
{
  "type": "done",
  "result": { "...": "与 POST /api/sync/slice 响应相同" }
}
```

#### `error`

```json
{ "type": "error", "message": "未配置 COMTRADE_API_KEY" }
```

**curl 示例**

```bash
curl -N -X POST http://127.0.0.1:8000/api/sync/slice/stream \
  -H "Content-Type: application/json" \
  -d '{"reporter_code":842,"year":2024,"freq_code":"M","month":12}'
```

---

## 8. 缓存策略（同步相关）

| 切片 status | 默认行为 | TTL |
|-------------|----------|-----|
| `ok` | 不重复请求 Comtrade | 永久（除非 `force_refresh`） |
| `empty` | 不重复请求 Comtrade | 7 天 |
| `error` | 不重复请求 Comtrade | 1 天 |

命中缓存时，切片结果中 `cached: true`，且 `records_upserted: 0`。

`empty` 状态**不会**在 `trade_records` 中写入明细，仅记录在 `data_slices`。

---

## 9. 错误格式

HTTP 4xx / 5xx 通常返回：

```json
{
  "detail": "错误说明"
}
```

---

## 10. 快速调用示例

```bash
# 健康检查
curl http://127.0.0.1:8000/api/health

# 查询美国 2024 年 12 月进口（本地库）
curl "http://127.0.0.1:8000/api/trade?freq_code=M&reporter_code=842&year=2024&month=12&flow_code=M"

# 同步美国 2024 年 12 月（进出口）
curl -X POST http://127.0.0.1:8000/api/sync/slice \
  -H "Content-Type: application/json" \
  -d '{"reporter_code":842,"year":2024,"freq_code":"M","month":12}'

# 导出当前筛选结果为 xlsx
curl -o export.xlsx "http://127.0.0.1:8000/api/trade/export?freq_code=M&reporter_code=842&year=2024&month=12"
```
