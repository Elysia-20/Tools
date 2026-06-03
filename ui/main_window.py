import logging
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QTabWidget, QStatusBar, QProgressBar, QMessageBox
)

from .tabs import (
    DomainExtractorTab,
    UrlToolsTab,
    UrlCheckerTab,
    LogTab,
)


class IntegratedSecurityTool(QMainWindow):
    def __init__(self, log_bus=None, log_handler=None):
        super().__init__()
        self.setWindowTitle('Tools')
        self.setGeometry(100, 100, 1366, 768)

        # 日志总线（可选）：由 main.py 创建并传入。若为 None 则不显示日志标签页
        self._log_bus = log_bus
        self._log_handler = log_handler

        # 初始化
        self.init_ui()
            
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # 创建标签页
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # 创建各个标签页（使用拆分后的模块化组件）
        self.domain_tab = DomainExtractorTab(self)
        self.tab_widget.addTab(self.domain_tab, "域名提取")

        self.url_tools_tab = UrlToolsTab(self)
        self.tab_widget.addTab(self.url_tools_tab, "URL工具")

        self.url_checker_tab = UrlCheckerTab(self)
        self.tab_widget.addTab(self.url_checker_tab, "URL检查")

        # 日志标签页（仅在 log_bus 已注入时显示）
        self.log_tab = None
        if self._log_bus is not None:
            self.log_tab = LogTab(self, self._log_bus)
            self.tab_widget.addTab(self.log_tab, "日志")

        # 创建状态栏
        self.create_status_bar()


    def create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

        self.status_bar.showMessage("就绪")

    def copy_table_selection(self, table_widget):
        # 通用的表格选择复制函数（兼容 QTableWidget 和 QTableView）
        try:
            indexes = table_widget.selectionModel().selectedIndexes()
            if not indexes:
                # 尝试获取当前单元格
                current = table_widget.currentIndex()
                if current.isValid():
                    text = current.data(Qt.ItemDataRole.DisplayRole) or ''
                    if text:
                        QApplication.clipboard().setText(str(text))
                return

            selected_cells = {}
            for idx in indexes:
                row, col = idx.row(), idx.column()
                if table_widget.isRowHidden(row):
                    continue
                cell_text = str(idx.data(Qt.ItemDataRole.DisplayRole) or '')
                selected_cells.setdefault(row, {})[col] = cell_text

            if not selected_cells:
                return

            # 构造复制文本
            min_col = min(min(cols.keys()) for cols in selected_cells.values())
            max_col = max(max(cols.keys()) for cols in selected_cells.values())

            lines = []
            for row in sorted(selected_cells.keys()):
                row_data = []
                for col in range(min_col, max_col + 1):
                    row_data.append(selected_cells[row].get(col, ''))
                lines.append('\t'.join(row_data))

            text = '\r\n'.join(lines)
            if text:
                QApplication.clipboard().setText(text)
                self.status_bar.showMessage(f'已复制 {len(lines)} 行数据', 2000)
        except Exception as e:
            QMessageBox.warning(self, '复制失败', f'复制数据时出错：{str(e)}')
            
    def copy_row_data(self, table_widget, row):
        # 复制指定行的所有数据（兼容 QTableWidget 和 QTableView）
        model = table_widget.model()
        if row < 0 or row >= model.rowCount():
            return

        row_data = []
        for col in range(model.columnCount()):
            value = model.index(row, col).data(Qt.ItemDataRole.DisplayRole)
            row_data.append(str(value) if value is not None else '')

        text = '\t'.join(row_data)
        if text:
            QApplication.clipboard().setText(text)

    def closeEvent(self, event):
        # 关窗清理：先并行触发所有 worker 的 cancel（仅设置标志，不等待），
        # 让所有 worker 在同一时间窗内开始退出；之后再串行调用 cleanup_workers
        # 处理 disconnect/deleteLater。这样总等待时间不再是各 tab 之和。
        try:
            from workers import UrlCheckWorker
            close_wait_ms = int((UrlCheckWorker.MAX_TOTAL_TIME + UrlCheckWorker.READ_TIMEOUT + 1) * 1000)
        except Exception:
            close_wait_ms = 30000

        workers_to_cancel = []

        url_tab = getattr(self, 'url_checker_tab', None)
        if url_tab is not None:
            workers_to_cancel.extend(getattr(url_tab, '_running_workers', []) or [])
            workers_to_cancel.extend(getattr(url_tab, '_orphaned_workers', []) or [])

        # Phase 1: 并行 cancel
        for w in workers_to_cancel:
            try:
                if hasattr(w, 'cancel'):
                    w.cancel()
            except Exception:
                pass

        # 让 cancel 信号尽快被各线程感知
        QApplication.processEvents()

        # Phase 2: 各 tab 的清理（disconnect/wait/deleteLater）。各 wait 此时
        # 大概率已经因 cancel 提前返回，串行执行也很快。
        for tab_name in ('url_checker_tab',):
            tab = getattr(self, tab_name, None)
            if tab is not None:
                try:
                    tab.cleanup_workers(wait_ms=close_wait_ms)
                except TypeError:
                    try:
                        tab.cleanup_workers()
                    except Exception:
                        pass
                except Exception:
                    pass

        # Phase 3: 兜底等待孤儿线程，避免 "Destroyed while still running"
        orphans = getattr(getattr(self, 'url_checker_tab', None), '_orphaned_workers', [])
        still_running_orphans = []
        if orphans:
            deadline = time.monotonic() + 1.0
            for w in orphans:
                try:
                    if w.isRunning():
                        remaining = max(0, int((deadline - time.monotonic()) * 1000))
                        if remaining > 0:
                            w.wait(remaining)
                    if w.isRunning():
                        still_running_orphans.append(w)
                except (RuntimeError, Exception):
                    pass

        if still_running_orphans:
            try:
                self.status_bar.showMessage(
                    f"仍有 {len(still_running_orphans)} 个URL检查线程未结束，已取消任务，请稍后再关闭",
                    3000,
                )
            except Exception:
                pass
            event.ignore()
            return

        # Phase 4: 日志标签页清理 + 从 logging 系统移除我们的 handler。
        # 必须在 super().closeEvent() 之前完成，避免 worker 后续 logger 调用
        # 通过 bus 转发到已销毁的 LogTab QObject
        if getattr(self, 'log_tab', None) is not None:
            try:
                self.log_tab.cleanup()
            except Exception:
                pass
        if self._log_handler is not None:
            try:
                logging.getLogger().removeHandler(self._log_handler)
            except Exception:
                pass
            self._log_handler = None

        super().closeEvent(event)
