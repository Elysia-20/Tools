from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING

from PyQt6 import sip
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QTableWidgetItem

from utils import get_logger
from workers import UrlCheckWorker

if TYPE_CHECKING:
    from .url_checker_tab import UrlCheckerTab


logger = get_logger("url_check_run_controller")


_WORKER_REFS: list[UrlCheckWorker] = []


def _release_worker_ref(worker: UrlCheckWorker) -> None:
    try:
        _WORKER_REFS.remove(worker)
    except ValueError:
        pass


def _retain_worker_until_finished(worker: UrlCheckWorker) -> None:
    # parent=None 的 QThread 需要强引用撑到 finished，否则 Python wrapper
    # 可能在线程结束前被回收。
    if worker in _WORKER_REFS:
        return
    _WORKER_REFS.append(worker)
    try:
        worker.finished.connect(lambda w=worker: _release_worker_ref(w))
    except (RuntimeError, TypeError):
        _release_worker_ref(worker)


class UrlCheckRunController:
    def __init__(self, tab: "UrlCheckerTab") -> None:
        self.tab = tab

    def start_check(self) -> None:
        tab = self.tab

        if tab._running_workers or tab._pending_tasks:
            tab._run_token += 1
            tab._stop_requested = True
            tab._terminate_running_workers(wait_ms=200)
            tab._pending_tasks.clear()
            tab._reset_run_buffers()

        urls = tab._collect_urls()
        if not urls:
            tab.main_window.status_bar.showMessage("请输入要检查的URL", 2000)
            return

        if not self._confirm_internal_access():
            return

        tab._run_token += 1

        tab._reset_run_buffers()
        if not tab._sync_request_options_from_ui():
            return

        tab._pending_tasks = deque((i, url) for i, url in enumerate(urls))
        tab._running_workers.clear()
        tab._stop_requested = False
        tab._total_urls = len(urls)
        tab._completed_urls = 0

        tab.url_table.setSortingEnabled(False)
        tab.url_table.setRowCount(len(urls))
        for i, url in enumerate(urls):
            item = QTableWidgetItem(url)
            item.setData(Qt.ItemDataRole.UserRole, i)
            tab.url_table.setItem(i, 0, item)

        self.update_url_progress(status="运行中...")
        tab._launch_workers()

    def launch_workers(self) -> None:
        tab = self.tab

        if tab._stop_requested:
            return

        while (
            len(tab._running_workers) < tab.thread_spin.value()
            and tab._pending_tasks
            and not tab._stop_requested
        ):
            row, url = tab._pending_tasks.popleft()
            worker = UrlCheckWorker(
                row,
                url,
                parent=None,
                verify_ssl=tab.ssl_verify_checkbox.isChecked(),
                allow_internal=tab.allow_internal_checkbox.isChecked(),
                downgrade_https=tab.https_downgrade_checkbox.isChecked(),
                compute_full_content_length=tab.full_length_checkbox.isChecked(),
                follow_meta_refresh=tab.follow_meta_refresh_checkbox.isChecked(),
                user_agent=tab._url_check_user_agent,
                cookie=tab._url_check_cookie,
            )
            _retain_worker_until_finished(worker)
            worker.run_token = tab._run_token
            worker.result_signal.connect(tab.on_worker_result)
            worker.finished.connect(worker.deleteLater)
            worker.start()
            tab._running_workers.append(worker)

        if not tab._running_workers and not tab._pending_tasks and not tab._stop_requested:
            if not tab._pending_results:
                tab.url_table.setSortingEnabled(True)
                tab._completed_urls = tab._total_urls
                self.update_url_progress(status="完成")
                tab.main_window.status_bar.showMessage("URL检查完成")
        else:
            self.update_url_progress(status="运行中...")

    def on_worker_result(
        self,
        sender,
        row: int,
        final_url: str,
        status: str,
        title: str,
        banner: str,
        ip: str,
        error: str,
        length: str,
    ) -> None:
        tab = self.tab

        if sender is not None and hasattr(sender, "run_token") and sender.run_token != tab._run_token:
            if isinstance(sender, UrlCheckWorker) and sender in tab._running_workers:
                try:
                    tab._running_workers.remove(sender)
                except ValueError:
                    pass
            return

        if isinstance(sender, UrlCheckWorker) and sender in tab._running_workers:
            try:
                tab._running_workers.remove(sender)
            except ValueError:
                pass
        else:
            tab._running_workers = [w for w in tab._running_workers if w.row != row]
        if tab._completed_urls < tab._total_urls:
            tab._completed_urls += 1

        tab._pending_results.append((row, final_url, ip, status, title, banner, length, error))
        if not tab._flush_timer.isActive():
            tab._flush_timer.start()

        if not tab._stop_requested:
            tab._launch_workers()

    def flush_pending_results(self) -> None:
        tab = self.tab

        if not tab._pending_results:
            tab._flush_timer.stop()
            return

        batch = tab._pending_results
        tab._pending_results = []

        tab.url_table.setUpdatesEnabled(False)
        try:
            for row, final_url, ip, status, title, banner, length, error in batch:
                target_row = self.find_table_row_by_original_index(row)
                if target_row < 0:
                    if 0 <= row < tab.url_table.rowCount():
                        target_row = row
                    else:
                        continue
                for c, text in enumerate(
                    (final_url or "", ip or "", status or "", title or "", banner or "", length or "", error or ""),
                    start=1,
                ):
                    item = QTableWidgetItem(text)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    tab.url_table.setItem(target_row, c, item)
        finally:
            tab.url_table.setUpdatesEnabled(True)

        if tab._stop_requested:
            tab._flush_timer.stop()
            tab.url_table.setSortingEnabled(True)
            self.update_url_progress(status="已停止")
        elif not tab._running_workers and not tab._pending_tasks:
            tab._flush_timer.stop()
            tab.url_table.setSortingEnabled(True)
            tab._completed_urls = tab._total_urls
            self.update_url_progress(status="完成")
            tab.main_window.status_bar.showMessage("URL检查完成")
        else:
            self.update_url_progress(status="运行中...")

    def stop_check(self) -> None:
        tab = self.tab

        tab._run_token += 1
        tab._stop_requested = True
        tab._flush_timer.stop()
        tab._flush_pending_results()
        tab._terminate_running_workers(wait_ms=300)
        tab._pending_tasks.clear()
        tab.url_table.setSortingEnabled(True)
        self.update_url_progress(status="已停止")
        tab.main_window.status_bar.showMessage("URL检查已停止")

    def terminate_running_workers(self, wait_ms: int = 300) -> None:
        tab = self.tab

        if not tab._running_workers:
            return

        tab._running_workers = [w for w in tab._running_workers if not sip.isdeleted(w)]
        if not tab._running_workers:
            return

        initial_count = len(tab._running_workers)

        for worker in tab._running_workers:
            try:
                worker.cancel()
            except (RuntimeError, Exception):
                pass

        if wait_ms > 0:
            deadline = time.monotonic() + (wait_ms / 1000)
            for worker in list(tab._running_workers):
                if sip.isdeleted(worker):
                    continue
                if worker.isRunning():
                    remaining = max(0, int((deadline - time.monotonic()) * 1000))
                    if remaining > 0:
                        worker.wait(remaining)
                QApplication.processEvents()

        still_running = [w for w in tab._running_workers if not sip.isdeleted(w) and w.isRunning()]
        stopped_count = initial_count - len(still_running)

        if still_running:
            logger.warning(
                f"线程清理: {stopped_count}/{initial_count} 已停止, "
                f"{len(still_running)} 个线程未响应 cancel() 信号"
            )
            for worker in still_running:
                try:
                    worker.result_signal.disconnect()
                except (TypeError, RuntimeError):
                    pass
                try:
                    worker.setParent(None)
                except (RuntimeError, TypeError):
                    pass
                _retain_worker_until_finished(worker)
                worker.finished.connect(worker.deleteLater)

        if not hasattr(tab, "_orphaned_workers"):
            tab._orphaned_workers = []
        tab._orphaned_workers = [w for w in tab._orphaned_workers if not sip.isdeleted(w) and w.isRunning()]
        tab._orphaned_workers.extend(still_running)
        tab._running_workers = []

    def retry_failed(self) -> None:
        tab = self.tab

        if tab._running_workers or tab._pending_tasks:
            tab.main_window.status_bar.showMessage("当前正在运行中，请等待完成或先停止后再重试", 2500)
            return

        failed_urls = []
        for row in range(tab.url_table.rowCount()):
            if not self._should_retry_row(row):
                continue
            url_item = tab.url_table.item(row, 0)
            if url_item and url_item.text().strip():
                original_row = url_item.data(Qt.ItemDataRole.UserRole)
                if not isinstance(original_row, int):
                    original_row = row
                    url_item.setData(Qt.ItemDataRole.UserRole, original_row)
                failed_urls.append((original_row, url_item.text().strip()))
        if not failed_urls:
            tab.main_window.status_bar.showMessage("没有需要重试的失败项", 2000)
            return

        if not tab._sync_request_options_from_ui():
            return

        tab._run_token += 1
        tab._reset_run_buffers()
        tab.url_table.setSortingEnabled(False)
        tab._total_urls = len(failed_urls)
        tab._completed_urls = 0
        tab._pending_tasks = deque(failed_urls)
        tab._stop_requested = False
        self.update_url_progress(status="重试中...")
        tab._launch_workers()

    def cleanup_workers(self, wait_ms: int = 2000) -> None:
        tab = self.tab

        tab._run_token += 1
        tab._stop_requested = True
        tab._flush_timer.stop()
        tab._pending_results.clear()
        tab._pending_tasks.clear()
        tab._terminate_running_workers(wait_ms=wait_ms)

    def clear_all(self) -> None:
        tab = self.tab

        tab.stop_check()
        tab.url_textedit.clear()
        tab.url_table.setRowCount(0)
        tab._pending_tasks.clear()
        tab._pending_results.clear()
        tab._total_urls = 0
        tab._completed_urls = 0
        tab._stop_requested = False
        tab._last_filter_conditions = []
        self.update_url_progress(status="就绪")
        if hasattr(tab, "btn_retry_failed"):
            tab.btn_retry_failed.setEnabled(True)
        tab.main_window.status_bar.showMessage("已清空URL检查数据", 2000)

    def update_url_progress(self, status: str | None = None) -> None:
        tab = self.tab

        if tab._total_urls <= 0:
            tab.main_window.status_bar.showMessage(status or "就绪")
            tab.main_window.progress_bar.setVisible(False)
            return

        percentage = (tab._completed_urls / tab._total_urls) * 100
        running = len(tab._running_workers)
        pending = len(tab._pending_tasks)
        prefix = status or "运行中"

        is_active = bool(running or pending)
        tab.main_window.progress_bar.setVisible(is_active)
        if is_active:
            tab.main_window.progress_bar.setRange(0, 0)

        tab.main_window.status_bar.showMessage(
            f"URL检查{prefix} {percentage:.1f}% ({tab._completed_urls}/{tab._total_urls})"
            f" | 线程: {running}  待处理: {pending}"
        )

        if hasattr(tab, "btn_retry_failed"):
            tab.btn_retry_failed.setEnabled(not (tab._running_workers or tab._pending_tasks))

    def find_table_row_by_original_index(self, original_row: int) -> int:
        tab = self.tab

        for table_row in range(tab.url_table.rowCount()):
            item = tab.url_table.item(table_row, 0)
            if item is None:
                continue
            if item.data(Qt.ItemDataRole.UserRole) == original_row:
                return table_row
        return -1

    def _confirm_internal_access(self) -> bool:
        tab = self.tab

        if not tab.allow_internal_checkbox.isChecked() or tab._internal_test_confirmed:
            return True

        choice = QMessageBox.warning(
            tab,
            "风险提示",
            "你已开启“允许内网/本机地址”。\n\n"
            "这将允许访问 127.0.0.1/localhost 及内网地址，可能导致误访问敏感服务或形成内网探测行为。\n"
            "请确认你已获得授权并了解风险。\n\n"
            "是否继续开启？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            tab.allow_internal_checkbox.setChecked(False)
            return False

        tab._internal_test_confirmed = True
        return True

    def _should_retry_row(self, row: int) -> bool:
        tab = self.tab

        status_item = tab.url_table.item(row, 3)
        err_item = tab.url_table.item(row, 7)
        status_text = status_item.text().strip() if status_item else ""
        err_text = err_item.text().strip() if err_item else ""

        if not status_text:
            return bool(err_text)

        try:
            status_code = int(status_text)
        except ValueError:
            return True

        if status_code >= 500:
            return True
        if err_text.startswith("安全拦截:") or err_text.startswith("ERR_"):
            return True

        return False
