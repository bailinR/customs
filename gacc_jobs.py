"""Background job runner for GACC Playwright fetch."""

from __future__ import annotations

import threading
from typing import Callable

from gacc_browser_watch import BrowserClosedError
from gacc_fetcher import fetch_gacc_csv
from gacc_models import GaccQueryParams
from gacc_parser import parse_gacc_csv
from gacc_storage import GaccStorage

_lock = threading.Lock()
_running: set[str] = set()


def _set_status(storage: GaccStorage, job_id: str, message: str, *, status: str | None = None) -> None:
    storage.update_job(job_id, status=status, message=message)


def run_gacc_job(job_id: str, params: GaccQueryParams, storage: GaccStorage | None = None) -> None:
    storage = storage or GaccStorage()
    try:
        storage.update_job(job_id, status="running", message="任务启动…")

        def on_status(message: str) -> None:
            if "验证码" in message:
                status = "waiting_captcha"
            elif "加载" in message or "渲染" in message or "等待" in message:
                status = "loading"
            else:
                status = "running"
            _set_status(storage, job_id, message, status=status)

        csv_path = fetch_gacc_csv(params, job_id=job_id, on_status=on_status)
        storage.update_job(job_id, status="parsing", message="正在解析 CSV…")
        records = parse_gacc_csv(csv_path, job_id=job_id, params=params)
        if not records:
            raise RuntimeError("CSV 解析结果为空，请检查查询条件或导出格式")
        count = storage.insert_records(records)
        storage.update_job(
            job_id,
            status="success",
            message=f"已导入 {count} 条记录 · CSV: {csv_path.resolve()}",
            record_count=count,
            finished=True,
        )
    except BrowserClosedError as exc:
        storage.update_job(
            job_id,
            status="error",
            message="采集已中止",
            error_message=str(exc),
            finished=True,
        )
    except Exception as exc:
        storage.update_job(
            job_id,
            status="error",
            message="采集失败",
            error_message=str(exc),
            finished=True,
        )
    finally:
        with _lock:
            _running.discard(job_id)


def start_gacc_job(params: GaccQueryParams, storage: GaccStorage | None = None) -> str:
    storage = storage or GaccStorage()
    job_id = storage.create_job(params)
    with _lock:
        if job_id in _running:
            raise RuntimeError("任务已在运行")
        _running.add(job_id)
    thread = threading.Thread(
        target=run_gacc_job,
        args=(job_id, params),
        kwargs={"storage": storage},
        daemon=True,
        name=f"gacc-{job_id}",
    )
    thread.start()
    return job_id
