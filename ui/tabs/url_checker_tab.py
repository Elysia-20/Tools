from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget

from workers import UrlCheckWorker
from .url_check_run_controller import UrlCheckRunController
from .url_checker_input_controller import UrlCheckerInputController
from .url_checker_table_controller import UrlCheckerTableController
from .url_checker_ui_builder import UrlCheckerUiBuilder


class UrlCheckerTab(QWidget):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        self._pending_tasks: Deque[tuple[int, str]] = deque()
        self._running_workers: List[UrlCheckWorker] = []
        self._stop_requested = False
        self._total_urls = 0
        self._completed_urls = 0
        self._last_filter_conditions: List[Dict[str, Any]] = []
        self._internal_test_confirmed = False
        self._run_token = 0
        self._url_check_user_agent = "Mozilla/5.0"
        self._url_check_cookie = ""

        self._input_controller = UrlCheckerInputController(self)
        self._run_controller = UrlCheckRunController(self)
        self._table_controller = UrlCheckerTableController(self)
        self._ui_builder = UrlCheckerUiBuilder(self)

        self._pending_results: List[tuple] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(150)
        self._flush_timer.timeout.connect(self._flush_pending_results)

        self._build_ui()

    def _build_ui(self):
        self._ui_builder.build()

    def on_ua_changed(self, idx: int):
        return self._input_controller.on_ua_changed(idx)

    def _get_user_agent(self) -> str:
        return self._input_controller.get_user_agent()

    def get_current_ua(self) -> str:
        return self._input_controller.get_user_agent()

    def update_current_ua_label(self):
        return self._input_controller.update_current_ua_label()

    def randomize_ua(self):
        return self._input_controller.randomize_ua()

    def _generate_random_ua(self) -> str:
        return self._input_controller.generate_random_ua()

    def _collect_urls(self) -> List[str]:
        return self._input_controller.collect_urls()

    def _sync_request_options_from_ui(self) -> bool:
        return self._input_controller.sync_request_options_from_ui()

    def _reset_run_buffers(self) -> None:
        return self._input_controller.reset_run_buffers()

    def load_urls(self):
        return self._input_controller.load_urls()

    def start_check(self):
        return self._run_controller.start_check()

    def _update_url_progress(self, status: str | None = None):
        return self._run_controller.update_url_progress(status=status)

    def _launch_workers(self):
        return self._run_controller.launch_workers()

    def on_worker_result(
        self,
        row: int,
        final_url: str,
        status: str,
        title: str,
        banner: str,
        ip: str,
        error: str,
        length: str,
    ):
        return self._run_controller.on_worker_result(
            self.sender(),
            row,
            final_url,
            status,
            title,
            banner,
            ip,
            error,
            length,
        )

    def _find_table_row_by_original_index(self, original_row: int) -> int:
        return self._run_controller.find_table_row_by_original_index(original_row)

    def _flush_pending_results(self):
        return self._run_controller.flush_pending_results()

    def stop_check(self):
        return self._run_controller.stop_check()

    def _terminate_running_workers(self, wait_ms: int = 300) -> None:
        return self._run_controller.terminate_running_workers(wait_ms=wait_ms)

    def retry_failed(self):
        return self._run_controller.retry_failed()

    def clear_all(self):
        return self._run_controller.clear_all()

    def cleanup_workers(self, wait_ms: int = 2000):
        return self._run_controller.cleanup_workers(wait_ms=wait_ms)

    def export_results(self):
        return self._table_controller.export_results()

    def show_context_menu(self, pos):
        return self._table_controller.show_context_menu(pos)

    def auto_resize_all_columns(self):
        return self._table_controller.auto_resize_all_columns()

    def auto_resize_column(self, logical_index: int):
        return self._table_controller.auto_resize_column(logical_index)

    def _open_url(self, url: str):
        return self._table_controller.open_url(url)

    def open_advanced_filter_dialog(self):
        return self._table_controller.open_advanced_filter_dialog()

    def advanced_filter_table(self, conditions: List[Dict[str, Any]]):
        return self._table_controller.advanced_filter_table(conditions)

    def clear_advanced_filter(self):
        return self._table_controller.clear_advanced_filter()
