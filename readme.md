# customsR

各国海关 / 贸易数据同步与查询 MVP：**UN Comtrade** 按需入库 + **中国海关总署** stats.customs.gov.cn 在线查询采集，Vue 3 前端统一操作。

---

## 快速开始

```powershell
cd d:\project\thinking\customsR
pip install -r requirements.txt
# 在项目根目录创建 .env（见下方配置）
```

`.env` 至少配置 Comtrade Key（[注册](https://comtradedeveloper.un.org/)）：

```env
COMTRADE_API_KEY=你的key
```

```powershell
# 终端 1：API
python -m uvicorn api.main:app --reload --port 8000

# 终端 2：前端
cd web && npm install && npm run dev
```

浏览器打开 http://localhost:5173 · API 文档 http://127.0.0.1:8000/docs · 详细接口见 [docs/API.md](docs/API.md)

```powershell
python -m pytest tests/ -v
```

---

## 功能概览

| 模块                 | 说明                                                                           |
| -------------------- | ------------------------------------------------------------------------------ |
| **Comtrade 同步**    | 选报告国 / 年或月 / 进出口，从官方 API 拉取写入 SQLite；支持强制刷新、SSE 进度 |
| **贸易查询**         | 只读本地库，筛选 + 分页 + 导出 xlsx                                            |
| **同步缓存**         | 查看 `data_slices`：已同步 / 官网暂无（负缓存）/ 失败可重试                    |
| **海关在线查询**     | 仿 stats.customs.gov.cn 筛选 → Playwright 弹窗 → **自动/手动滑块** → CSV 入库  |
| **定时任务（前端）** | Comtrade 与海关侧边栏均可设「每日 HH:mm」自动执行（**需保持浏览器页签打开**）  |

---

## 数据源

| 来源                                                 | 状态        | 说明                                            |
| ---------------------------------------------------- | ----------- | ----------------------------------------------- |
| [UN Comtrade API](https://comtrade.un.org/)          | ✅ 主数据源 | 需 `COMTRADE_API_KEY`                           |
| [stats.customs.gov.cn](http://stats.customs.gov.cn/) | ✅ 已接入   | Playwright + OpenCV 滑块；SSL 异常时需本机 Edge |
| US Census API                                        | ❌          | 国内常见 403                                    |
| english.customs.gov.cn                               | 未接入      | 备用                                            |

---

## 海关采集（GACC）

### 流程

1. 前端「海关在线查询」→ 填筛选条件 → **开始查询**
2. 本机弹出 **Edge / Chrome**（默认有界面，便于验证码）
3. 自动识别验证码缺口（**纯白块区域**）并拖动滑块；失败可同图微调或改用手动
4. 验证通过后自动下载 CSV → 解析入库 → 左侧表格展示

### Playwright 安装（首次）

```powershell
pip install playwright
python -m playwright install msedge
```

### 验证码相关配置（`.env`）

| 变量                             | 默认                | 说明                                          |
| -------------------------------- | ------------------- | --------------------------------------------- |
| `GACC_CAPTCHA_AUTO`              | `true`              | `false` 则全程手动滑块                        |
| `GACC_CAPTCHA_AUTO_MAX_ATTEMPTS` | `5`                 | 自动失败多少次后刷新换图 / 转手动             |
| `GACC_CAPTCHA_FALLBACK_MANUAL`   | `true`              | 自动失败后是否提示用户手动完成                |
| `GACC_CAPTCHA_OFFSET_PX`         | `0`                 | 滑块轨道像素微调（偏左负、偏右正，常见 ±2~5） |
| `GACC_CAPTCHA_TIMEOUT_SEC`       | `300`               | 单次验证码等待上限（秒）                      |
| `GACC_BROWSER_CHANNEL`           | `msedge`（Windows） | 也可 `chrome` / 留空用 Chromium               |
| `GACC_BROWSER_HEADLESS`          | `false`             | 无头模式（验证码场景不建议）                  |

诊断脚本（验证码弹出后运行）：

```powershell
python scripts/gacc_captcha_debug.py
```

输出 `data/gacc_captcha_debug.json` 与 `data/captcha_debug_images/` 截图。

### 相关代码

| 文件                    | 职责                               |
| ----------------------- | ---------------------------------- |
| `gacc_fetcher.py`       | Playwright 打开查询页、提交、下载  |
| `gacc_captcha.py`       | 自动/手动验证码流程                |
| `gacc_slider_solver.py` | OpenCV 纯白缺口检测 + 滑块距离换算 |
| `gacc_jobs.py`          | 后台任务与状态回调                 |

---

## 定时任务（前端）

在 **Comtrade 同步侧栏** 与 **海关筛选侧栏** 底部可勾选「启用每日定时」，设置时 / 分。

- 配置保存在浏览器 `localStorage`（`customsR.schedule.comtrade` / `.gacc`）
- 每 15 秒检查一次，到点且表单完整则自动触发同步或海关查询
- **限制**：关闭页签或浏览器后不会执行；服务端定时需另行接入 APScheduler / 系统 cron

---

## 项目结构

```
customsR/
├── api/main.py              # FastAPI
├── comtrade_client.py       # Comtrade 年度/月度 API
├── comtrade_meta.py         # 国家、年份元数据
├── sync_service.py          # 按需切片同步、SSE
├── storage.py               # trade_records / data_slices
├── trade_query.py           # 贸易查询 SQL
├── trade_export.py          # xlsx 导出
├── gacc_fetcher.py          # 海关 Playwright 采集
├── gacc_captcha.py          # 验证码（自动 + 手动）
├── gacc_slider_solver.py    # 滑块缺口识别
├── gacc_parser.py / gacc_storage.py / gacc_jobs.py
├── sync.py                  # 可选：五国近 3 年年度批量预同步
├── scripts/gacc_captcha_debug.py
├── docs/API.md
├── web/                     # Vue 3 + Vite
├── data/customs.db          # SQLite（git 忽略）
└── output/                  # 脚本导出（git 忽略）
```

---

## 概念说明

| 概念                     | 定义                                                     |
| ------------------------ | -------------------------------------------------------- |
| **海关数据（Comtrade）** | 各国官方进出口贸易统计，货值美元计                       |
| **商品分类**             | HS；当前 Comtrade 同步使用 `cmdCode=TOTAL`（全商品合计） |
| **切片**                 | 最小同步单位：报告国 + 年/月 + 进出口 + 年度/月度        |
| **负缓存**               | 官网返回空结果时记 `empty`，7 天内不重复请求             |

---

## 数据存储（SQLite）

**路径**：`data/customs.db`

### trade_records

Comtrade 贸易明细。

| 字段                            | 说明                      |
| ------------------------------- | ------------------------- |
| `reporter_code`                 | 报告国 UN M49             |
| `partner_code` / `partner_name` | 伙伴国（`0` = World）     |
| `freq_code`                     | `A` 年度 / `M` 月度       |
| `year` / `month`                | 年度 `month=0`；月度 1–12 |
| `flow_code`                     | `X` 出口 / `M` 进口       |
| `trade_value_usd`               | 贸易额（美元）            |

### data_slices

同步状态（有无论文都会记录）。

| status  | 行为                   |
| ------- | ---------------------- |
| `ok`    | 默认不再请求 Comtrade  |
| `empty` | 7 天内不重复（负缓存） |
| `error` | 1 天内不重复           |

勾选「强制刷新」或 TTL 过期后重新请求。

### gacc_trade_records / gacc_query_jobs

海关 HS 8 位级明细（伙伴、贸易方式、注册地、数量、货值等），见库表字段或 [docs/API.md](docs/API.md)。

### SQL 示例

```sql
-- 美国 2024 年 12 月总进口（World）
SELECT trade_value_usd FROM trade_records
WHERE reporter_code = 842 AND year = 2024 AND month = 12
  AND freq_code = 'M' AND flow_code = 'M' AND partner_code = 0;

-- 中国 2025 年度是否被标记为官网暂无
SELECT * FROM data_slices
WHERE reporter_code = 156 AND year = 2025 AND freq_code = 'A';
```

---

## 同步方式

| 方式             | 说明                                                                         |
| ---------------- | ---------------------------------------------------------------------------- |
| **Web 按需同步** | 约 252 个报告国；年度 `A` / 月度 `M`；`POST /api/sync/slice/stream` SSE 进度 |
| **sync.py**      | 可选：中美德英日近 3 **年度**，约 30 次 API/轮                               |
| **前端定时**     | 每日到点自动触发（见上文）                                                   |

---

## API 一览

完整说明见 **[docs/API.md](docs/API.md)**。

| 方法 | 路径                     | 说明         |
| ---- | ------------------------ | ------------ |
| GET  | `/api/health`            | 健康检查     |
| GET  | `/api/meta/filters`      | 查询页筛选项 |
| GET  | `/api/meta/sync-options` | 同步表单选项 |
| GET  | `/api/slices`            | 切片缓存分页 |
| POST | `/api/sync/slice/stream` | 同步（SSE）  |
| GET  | `/api/trade`             | 贸易数据查询 |
| GET  | `/api/trade/export`      | 导出 xlsx    |
| GET  | `/api/gacc/meta/options` | 海关筛选项   |
| POST | `/api/gacc/query`        | 发起海关采集 |
| GET  | `/api/gacc/jobs/{id}`    | 任务状态     |
| GET  | `/api/gacc/trade`        | 海关明细分页 |
