import os
import sys
import unittest
from collections import deque
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTableWidgetItem

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.tabs.url_checker_tab import UrlCheckerTab


class _FakeStatusBar:
    def __init__(self):
        self.last_message = ""

    def showMessage(self, message, timeout=0):
        self.last_message = message


class _FakeProgressBar:
    def __init__(self):
        self.visible = False
        self.range = (0, 100)

    def setVisible(self, visible):
        self.visible = bool(visible)

    def setRange(self, minimum, maximum):
        self.range = (minimum, maximum)


class _FakeMainWindow:
    def __init__(self):
        self.status_bar = _FakeStatusBar()
        self.progress_bar = _FakeProgressBar()

    def copy_table_selection(self, _table):
        return None


class TestUrlCheckerTabRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tab = UrlCheckerTab(_FakeMainWindow())
        self.addCleanup(self.tab.deleteLater)

    def _set_row(self, table_row, url, original_row, status="", error=""):
        url_item = QTableWidgetItem(url)
        url_item.setData(Qt.ItemDataRole.UserRole, original_row)
        self.tab.url_table.setItem(table_row, 0, url_item)
        self.tab.url_table.setItem(table_row, 3, QTableWidgetItem(status))
        self.tab.url_table.setItem(table_row, 7, QTableWidgetItem(error))

    def test_retry_failed_uses_original_row_index_after_sort(self):
        self.tab.url_table.setRowCount(2)
        # 模拟排序后视觉顺序与原始顺序不一致：第0行对应原始1，第1行对应原始0
        self._set_row(0, "b.example.com", 1, status="500")
        self._set_row(1, "a.example.com", 0, status="500")

        self.tab._launch_workers = MagicMock()
        self.tab._running_workers = []
        self.tab._pending_tasks = deque()

        self.tab.retry_failed()

        self.assertEqual(list(self.tab._pending_tasks), [(1, "b.example.com"), (0, "a.example.com")])
        self.assertEqual(self.tab._total_urls, 2)
        self.assertEqual(self.tab._completed_urls, 0)
        self.assertFalse(self.tab.url_table.isSortingEnabled())
        self.tab._launch_workers.assert_called_once()

    def test_flush_pending_results_maps_back_by_user_role(self):
        self.tab.url_table.setRowCount(2)
        # 模拟排序后顺序：row0->original1, row1->original0
        self._set_row(0, "b.example.com", 1)
        self._set_row(1, "a.example.com", 0)

        self.tab._stop_requested = False
        self.tab._running_workers = []
        self.tab._pending_tasks = deque()
        self.tab._total_urls = 2
        self.tab._completed_urls = 2
        self.tab._pending_results = [
            (0, "http://final-a", "1.1.1.1", "200", "A", "BA", "10", ""),
            (1, "http://final-b", "2.2.2.2", "500", "B", "BB", "20", "ERR_X"),
        ]

        self.tab._flush_pending_results()

        # original=0 应写到当前 table row=1
        self.assertEqual(self.tab.url_table.item(1, 1).text(), "http://final-a")
        self.assertEqual(self.tab.url_table.item(1, 2).text(), "1.1.1.1")
        self.assertEqual(self.tab.url_table.item(1, 3).text(), "200")
        # original=1 应写到当前 table row=0
        self.assertEqual(self.tab.url_table.item(0, 1).text(), "http://final-b")
        self.assertEqual(self.tab.url_table.item(0, 2).text(), "2.2.2.2")
        self.assertEqual(self.tab.url_table.item(0, 3).text(), "500")
        self.assertEqual(self.tab.url_table.item(0, 7).text(), "ERR_X")

    def test_retry_twice_then_stop_clears_pending_and_unlocks(self):
        self.tab.url_table.setRowCount(2)
        self._set_row(0, "a.example.com", 0, status="500")
        self._set_row(1, "b.example.com", 1, status="500")

        self.tab._launch_workers = MagicMock()
        self.tab._terminate_running_workers = MagicMock()
        self.tab._running_workers = []
        self.tab._pending_tasks = deque()

        # 第一次重试：应建立任务队列
        self.tab.retry_failed()
        self.assertEqual(self.tab._run_token, 1)
        first_pending = list(self.tab._pending_tasks)
        self.assertEqual(first_pending, [(0, "a.example.com"), (1, "b.example.com")])
        self.assertFalse(self.tab.url_table.isSortingEnabled())

        # 第二次重试（任务进行中）：应被拦截，不应覆盖原队列/递增 token
        self.tab.retry_failed()
        self.assertEqual(self.tab._run_token, 1)
        self.assertEqual(list(self.tab._pending_tasks), first_pending)
        self.assertIn("当前正在运行中", self.tab.main_window.status_bar.last_message)

        # 中途停止：应清空待处理并恢复排序
        self.tab.stop_check()
        self.assertEqual(self.tab._run_token, 2)
        self.assertTrue(self.tab._stop_requested)
        self.assertEqual(len(self.tab._pending_tasks), 0)
        self.assertTrue(self.tab.url_table.isSortingEnabled())
        self.tab._terminate_running_workers.assert_called_once()


    def test_start_check_clears_stale_pending_results_before_new_run(self):
        self.tab.url_textedit.setPlainText("https://fresh.example.com")
        self.tab._pending_results = [
            (0, "http://stale", "1.1.1.1", "200", "stale", "banner", "10", ""),
        ]
        self.tab._flush_timer.start()
        self.tab._launch_workers = MagicMock()

        self.tab.start_check()

        self.assertEqual(self.tab._pending_results, [])
        self.assertFalse(self.tab._flush_timer.isActive())
        self.assertEqual(list(self.tab._pending_tasks), [(0, "https://fresh.example.com")])
        self.tab._launch_workers.assert_called_once()

    @patch("ui.tabs.url_check_run_controller._retain_worker_until_finished")
    @patch("ui.tabs.url_check_run_controller.UrlCheckWorker")
    def test_launch_workers_creates_unparented_retained_worker(self, mock_worker_cls, mock_retain):
        worker = MagicMock()
        mock_worker_cls.return_value = worker
        self.tab._pending_tasks = deque([(0, "https://fresh.example.com")])
        self.tab._running_workers = []
        self.tab._stop_requested = False
        self.tab._total_urls = 1
        self.tab._completed_urls = 0
        self.tab.thread_spin.setValue(1)

        self.tab._launch_workers()

        _, kwargs = mock_worker_cls.call_args
        self.assertIsNone(kwargs["parent"])
        mock_retain.assert_called_once_with(worker)
        worker.result_signal.connect.assert_called_once_with(self.tab.on_worker_result)
        worker.finished.connect.assert_called_once_with(worker.deleteLater)
        worker.start.assert_called_once()
        self.assertIn(worker, self.tab._running_workers)

    def test_retry_failed_refreshes_request_options_and_clears_stale_results(self):
        self.tab.url_table.setRowCount(1)
        self._set_row(0, "a.example.com", 0, status="500")
        self.tab._launch_workers = MagicMock()
        self.tab._running_workers = []
        self.tab._pending_tasks = deque()
        self.tab._pending_results = [(0, "http://stale", "", "", "", "", "", "")]
        self.tab._url_check_user_agent = "stale-ua"
        self.tab._url_check_cookie = "stale=1"
        self.tab.ua_combo.setCurrentIndex(self.tab._custom_index)
        self.tab.ua_custom_edit.setText("Custom-UA/1.0")
        self.tab.cookie_edit.setText("session=abc")

        self.tab.retry_failed()

        self.assertEqual(self.tab._url_check_user_agent, "Custom-UA/1.0")
        self.assertEqual(self.tab._url_check_cookie, "session=abc")
        self.assertEqual(self.tab._pending_results, [])
        self.assertEqual(list(self.tab._pending_tasks), [(0, "a.example.com")])
        self.tab._launch_workers.assert_called_once()

    @patch("ui.tabs.url_checker_input_controller.QMessageBox.warning")
    def test_retry_failed_aborts_on_invalid_cookie(self, mock_warning):
        self.tab.url_table.setRowCount(1)
        self._set_row(0, "a.example.com", 0, status="500")
        self.tab._launch_workers = MagicMock()
        self.tab._running_workers = []
        self.tab._pending_tasks = deque()
        self.tab.cookie_edit.setText("bad\nvalue")

        self.tab.retry_failed()

        self.assertEqual(list(self.tab._pending_tasks), [])
        self.tab._launch_workers.assert_not_called()
        mock_warning.assert_called_once()

    @patch("ui.tabs.url_checker_table_controller.QMessageBox.warning")
    def test_export_results_warns_when_table_is_empty(self, mock_warning):
        self.tab.export_results()

        mock_warning.assert_called_once()

    @patch("ui.tabs.url_checker_table_controller.QMessageBox.information")
    def test_open_advanced_filter_dialog_shows_info_when_table_is_empty(self, mock_information):
        self.tab.open_advanced_filter_dialog()

        mock_information.assert_called_once()

    def test_clear_advanced_filter_restores_rows_and_conditions(self):
        self.tab.url_table.setRowCount(2)
        self.tab.url_table.setRowHidden(0, True)
        self.tab.url_table.setRowHidden(1, True)
        self.tab._last_filter_conditions = [{"field": "status", "operator": "contains", "value": "200"}]

        self.tab.clear_advanced_filter()

        self.assertFalse(self.tab.url_table.isRowHidden(0))
        self.assertFalse(self.tab.url_table.isRowHidden(1))
        self.assertEqual(self.tab._last_filter_conditions, [])

    def test_randomize_ua_switches_to_custom_and_updates_label(self):
        self.tab._input_controller.generate_random_ua = MagicMock(return_value="Random-UA/1.0")

        self.tab.randomize_ua()

        self.assertEqual(self.tab.ua_combo.currentIndex(), self.tab._custom_index)
        self.assertEqual(self.tab.ua_custom_edit.text(), "Random-UA/1.0")
        self.assertIn("Random-UA/1.0", self.tab.current_ua_label.text())
        self.assertIn("已生成随机 UA", self.tab.main_window.status_bar.last_message)

    @patch("ui.tabs.url_checker_input_controller.read_urls_from_txt")
    @patch("ui.tabs.url_checker_input_controller.QFileDialog.getOpenFileName")
    def test_load_urls_reads_file_and_updates_text(self, mock_get_open_file_name, mock_read_urls):
        mock_get_open_file_name.return_value = ("urls.txt", "Text Files (*.txt)")
        mock_read_urls.return_value = ["https://a.example.com", "https://b.example.com"]

        self.tab.load_urls()

        self.assertEqual(
            self.tab.url_textedit.toPlainText(),
            "https://a.example.com\nhttps://b.example.com",
        )
        self.assertIn("已加载 2 条 URL", self.tab.main_window.status_bar.last_message)

if __name__ == "__main__":
    unittest.main()
