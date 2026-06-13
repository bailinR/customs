# customsR — 各国海关/贸易数据同步 MVP

从 [UN Comtrade](https://comtrade.un.org/) 按需拉取各国进出口贸易统计，存入 SQLite，Web 查询与导出 Excel。

## 1. 问题定义

| 概念 | 本项目的定义 |
|------|-------------|
| **海关数据** | 各国官方**进出口贸易统计**（货值，美元计） |
| **商品分类** | HS 协调制度，`cmdCode=TOTAL` 表示全商品合计 |
| **实时** | 按需从 Comtrade 官方 API 拉取已发布数据；非 WebSocket 推送 |
| **切片** | 最小同步单位：报告国 + 年/月 + 进出口 + 年度/月度 |

## 2. 数据源

| 来源 | 状态 |
|------|------|
| **UN Comtrade API**（主） | ✅ 可用，需 `.env` 配置 Key |
| US Census API | ❌ 403 |
| **stats.customs.gov.cn**（中国） | ✅ Playwright 半自动（手动滑块验证码） |
| english.customs.gov.cn | 备用（未接入） |

## 3. 项目结构

```
customsR/
├── api/main.py           # FastAPI 服务
├── comtrade_client.py    # Comtrade 年度/月度 API
├── comtrade_meta.py      # 国家列表、年份范围
├── config.py             # 配置与标签
├── storage.py            # SQLite：trade_records / data_slices
├── sync_service.py       # 按需切片同步、SSE 进度
├── slice_meta.py         # 切片状态展示字段
├── trade_query.py        # 贸易查询 SQL 构建
├── trade_export.py       # xlsx 导出
├── gacc_fetcher.py       # 海关总署 Playwright 采集
├── gacc_parser.py        # 海关 CSV 解析
├── gacc_storage.py       # gacc_trade_records / gacc_query_jobs
├── gacc_jobs.py          # 后台采集任务
├── sync.py               # 可选：五国近 3 年年度批量预同步
├── docs/API.md           # API 详细文档
├── web/                  # Vue 3 前端
├── data/customs.db       # SQLite（git 忽略）
└── output/               # 脚本导出目录（git 忽略）
```

## 4. 使用方式

```powershell
cd d:\project\thinking\customsR
pip install -r requirements.txt

# 可选：预同步五国近 3 年年度数据
python sync.py

# 终端 1：API
python -m uvicorn api.main:app --reload --port 8000

# 终端 2：前端
cd web
npm install
npm run dev
```

浏览器打开 http://localhost:5173

```powershell
# 单元测试（缓存逻辑 + API 冒烟）
python -m pytest tests/ -v
```

| 区域 | 功能 |
|------|------|
| **左侧同步区** | 选国家 / 年度或月度 / 周期，从 Comtrade 拉取入库；支持强制刷新 |
| **数据查询** | 只读本地库，年度/月度筛选，导出 xlsx |
| **同步缓存** | 查看 `data_slices`：哪些组合已有数据、官网暂无（负缓存）、失败可重试 |
| **海关在线查询** | 仿 stats.customs.gov.cn 筛选 → Playwright 弹窗 → 手动验证码 → CSV 入库 |

`.env`：

```
COMTRADE_API_KEY=你的key

# 海关源（可选）
GACC_BASE_URL=http://stats.customs.gov.cn/
GACC_BROWSER_CHANNEL=msedge
GACC_BROWSER_HEADLESS=false
GACC_CAPTCHA_TIMEOUT_SEC=180
```

首次使用海关采集需安装 Playwright 浏览器：

```powershell
pip install playwright
python -m playwright install msedge
```

**海关采集流程**：前端「海关在线查询」Tab → 填筛选条件 → 查询 → **本机弹出 Edge/Chrome** → 手动完成滑动验证码 → 自动导出 CSV → 解析入库 → 页面展示。

**API 文档**：详见 [docs/API.md](docs/API.md)，或启动服务后访问 http://127.0.0.1:8000/docs

## 5. 数据存储（SQLite）

**库路径**: `data/customs.db`

### trade_records

贸易明细（有数据时写入）。

| 字段 | 说明 |
|------|------|
| `reporter_code` | 报告国 UN M49 |
| `partner_code` / `partner_name` | 伙伴国（`0` = World 合计） |
| `freq_code` | `A` 年度 / `M` 月度 |
| `year` / `month` | 年度 `month=0`；月度 1–12 |
| `flow_code` | `X` 出口 / `M` 进口 |
| `cmd_code` | 默认 `TOTAL`（全商品） |
| `trade_value_usd` | 贸易额（美元） |

### data_slices

同步任务状态 / 负缓存（**无论是否有明细都会记录**）。

| 字段 | 说明 |
|------|------|
| `reporter_code, year, month, flow_code, freq_code` | 切片唯一键 |
| `status` | `ok` / `empty` / `error` |
| `record_count` | 该切片写入条数 |
| `fetched_at` | 最近同步时间 |

**缓存策略**

| status | 行为 |
|--------|------|
| `ok` | 默认不再请求 Comtrade |
| `empty` | 7 天内不重复请求（负缓存） |
| `error` | 1 天内不重复请求 |

勾选「强制刷新」或 TTL 过期后会重新请求 API。

### gacc_trade_records / gacc_query_jobs

海关总署 `stats.customs.gov.cn` 采集结果（HS 8 位 + 伙伴 + 贸易方式 + 注册地）。

| 字段 | 说明 |
|------|------|
| `job_id` | 采集任务 ID |
| `hs_code` / `hs_name` | 商品编码 / 名称 |
| `partner_code` / `partner_name` | 贸易伙伴 |
| `trade_mode_*` | 贸易方式 |
| `reg_place_*` | 收发货人注册地 |
| `qty1` / `unit1` | 第一数量及单位 |
| `value` | 美元或人民币货值 |

### SQL 示例

```sql
-- 美国 2024 年 12 月总进口（World）
SELECT trade_value_usd FROM trade_records
WHERE reporter_code = 842 AND year = 2024 AND month = 12
  AND freq_code = 'M' AND flow_code = 'M' AND partner_code = 0;

-- 查看中国 2025 年度是否被标记为官网暂无
SELECT * FROM data_slices
WHERE reporter_code = 156 AND year = 2025 AND freq_code = 'A';
```

## 6. 同步方式

### Web 按需同步（主流程）

- 国家：Comtrade 参考表全部报告国（约 252 个）
- 年度：`freq_code=A`
- 月度：`freq_code=M`，可选单月或 `month=0`（全年 12 月 × 进出口 = 24 次 API）
- 进度：`POST /api/sync/slice/stream` SSE 推送

### sync.py（可选批量）

- 五国（中美德英日）近 3 **年度**数据
- 约 5 × 3 × 2 = 30 次 API / 轮

## 7. 已知局限

- 各国报送进度不同（如中国 2024 有数据、2025 常为空）
- 2025–2026 多数国家 Comtrade 尚无月度/年度数据，同步会得到 `empty` 负缓存
- 免费 Key：约 10 万条/次、500 次/天
- 当前仅 `cmdCode=TOTAL`，未做 HS 商品级细分

## 8. API 一览

完整参数、响应示例、SSE 事件见 **[docs/API.md](docs/API.md)**。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/meta/filters` | 查询页联动筛选项 |
| GET | `/api/meta/sync-options` | 同步表单选项 |
| GET | `/api/slices/meta` | 同步缓存页筛选项 |
| GET | `/api/slices` | 切片状态分页列表 |
| POST | `/api/sync/slice` | 同步（一次性 JSON） |
| POST | `/api/sync/slice/stream` | 同步（SSE 进度） |
| GET | `/api/trade` | 贸易数据分页查询 |
| GET | `/api/trade/export` | 导出 xlsx（最多 5 万条） |
| GET | `/api/gacc/meta/options` | 海关查询筛选项 |
| POST | `/api/gacc/query` | 发起海关 Playwright 采集 |
| GET | `/api/gacc/jobs/{id}` | 采集任务状态 |
| GET | `/api/gacc/trade` | 海关明细分页查询 |

## 9. 演示建议（面试 / 验收）

1. **USA · 2024 · Monthly · December** → 同步 → 查询 → 导出 xlsx  
2. **China · 2025 · Annual** → 同步 → 同步缓存页见 `empty` 负缓存  
3. **海关在线查询** → 进口 · 2024年12月 · 美元 → 弹窗验证码 → 查看 HS 级明细  
4. 同一组合再次同步 → 命中缓存，不重复打 API（除非强制刷新）

## 10. 扩展方向

- [x] 按需切片同步 + 空结果负缓存
- [x] 年度 / 月度 + All of year
- [x] SSE 同步进度
- [x] 查询结果导出 xlsx
- [x] 同步缓存页（data_slices）
- [x] 单元测试（`pytest`，见 `tests/`）
- [x] 海关总署 stats.customs.gov.cn（Playwright + 手动验证码）
- [ ] HS 商品级采集（Comtrade `cmdCode` 非 TOTAL）
- [ ] 中国海关英文站补充源
- [ ] APScheduler 定时同步
