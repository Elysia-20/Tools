# 日志标签页：实时查看应用日志输出
#
# 设计要点：
# - 接收 QtLogBus 信号，攒批刷新（100ms 一次），避免高频日志卡 UI
# - QPlainTextEdit + setMaximumBlockCount(5000) 限制内存
# - 按级别 + 按文本过滤
# - 自动滚动可关闭（用户向上看历史时不想被打断）
# - HTML 转义防止日志内容里的 <、& 破坏渲染
# - 关窗时 cleanup() 断开信号，避免 worker 线程访问已销毁 QObject

from __future__ import annotations

import html as html_module
from typing import List, Tuple

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LogTab(QWidget):
    # 实时日志查看标签页

    # 上限：达到后自动丢弃最旧的行（QPlainTextEdit 内置）
    MAX_LINES = 5000
    # 攒批刷新间隔，权衡 UI 流畅性与吞吐量
    FLUSH_INTERVAL_MS = 100

    LEVEL_COLORS = {
        'DEBUG': '#888888',
        'INFO': '#1a1a1a',
        'WARNING': '#c98a2b',
        'ERROR': '#c0392b',
        'CRITICAL': '#8e0000',
    }

    def __init__(self, main_window, log_bus, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._bus = log_bus

        # 待刷新缓冲（仅 main thread 写入；slot 由 queued connection 派发）
        self._pending: List[Tuple[str, str, str, str]] = []
        # 当前启用的级别（用户可勾选/取消）
        self._level_filter = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        self._text_filter: str = ""
        self._auto_scroll: bool = True
        # 标记是否已 cleanup，防止 cleanup 后误处理信号
        self._cleaned_up: bool = False

        self._build_ui()
        self._connect_bus()

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(self.FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start()

    # ---- UI ----

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # 工具栏：级别筛选 + 文本过滤 + 操作按钮
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        toolbar.addWidget(QLabel("级别:"))
        self._level_checkboxes = {}
        for level in ('DEBUG', 'INFO', 'WARNING', 'ERROR'):
            cb = QCheckBox(level)
            cb.setChecked(True)
            cb.toggled.connect(lambda checked, lvl=level: self._on_level_toggled(lvl, checked))
            self._level_checkboxes[level] = cb
            toolbar.addWidget(cb)
        # DEBUG 提示
        self._level_checkboxes['DEBUG'].setToolTip(
            "DEBUG 级别包含详细诊断（DNS失败、IP提取失败、HTTP头解析等内部细节），可能很多"
        )

        toolbar.addSpacing(10)
        toolbar.addWidget(QLabel("过滤:"))
        self._text_filter_edit = QLineEdit()
        self._text_filter_edit.setPlaceholderText("关键字过滤（logger 名或消息内容，不区分大小写）")
        self._text_filter_edit.textChanged.connect(self._on_text_filter_changed)
        self._text_filter_edit.setMaximumWidth(320)
        toolbar.addWidget(self._text_filter_edit)

        toolbar.addStretch()

        self._auto_scroll_cb = QCheckBox("自动滚动")
        self._auto_scroll_cb.setChecked(True)
        self._auto_scroll_cb.toggled.connect(self._on_auto_scroll_toggled)
        toolbar.addWidget(self._auto_scroll_cb)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(clear_btn)

        copy_btn = QPushButton("复制全部")
        copy_btn.clicked.connect(self._copy)
        toolbar.addWidget(copy_btn)

        save_btn = QPushButton("保存到文件")
        save_btn.clicked.connect(self._save)
        toolbar.addWidget(save_btn)

        layout.addLayout(toolbar)

        # 日志显示区
        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(self.MAX_LINES)
        self._view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # 等宽字体；exactMatch 失败时回退
        font = QFont("Consolas", 9)
        if not font.exactMatch():
            font = QFont("Courier New", 9)
        self._view.setFont(font)
        self._view.setStyleSheet("QPlainTextEdit { background-color: #fafafa; }")
        layout.addWidget(self._view, 1)

        # 状态行：当前显示行数 / 上限
        self._status_label = QLabel(f"等待日志... (最多保留 {self.MAX_LINES} 行)")
        self._status_label.setStyleSheet("color: #999; padding: 2px;")
        layout.addWidget(self._status_label)

    def _connect_bus(self):
        # 显式 QueuedConnection：bus 在 main thread 上，emit 来自 worker thread，
        # queued 保证 slot 在 main thread 执行（虽然默认行为也是这样，但显式更清楚）
        self._bus.record_emitted.connect(self._on_log_record, Qt.ConnectionType.QueuedConnection)

    # ---- 信号处理 ----

    def _on_log_record(self, level: str, name: str, message: str, timestamp: str):
        # 在 main thread 运行（queued connection）
        if self._cleaned_up:
            return
        self._pending.append((level, name, message, timestamp))
        # 兜底：极端情况下 flush 跟不上，限制 pending 上限避免内存爆涨
        if len(self._pending) > self.MAX_LINES:
            self._pending = self._pending[-self.MAX_LINES:]

    def _flush(self):
        if not self._pending:
            return
        batch = self._pending
        self._pending = []

        text_filter = self._text_filter.lower()

        # 关闭刷新提升性能
        self._view.setUpdatesEnabled(False)
        try:
            cursor = self._view.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)

            written = 0
            for level, name, message, timestamp in batch:
                if level not in self._level_filter:
                    continue
                if text_filter:
                    haystack = (name + ' ' + message).lower()
                    if text_filter not in haystack:
                        continue
                color = self.LEVEL_COLORS.get(level, '#000')
                # HTML 转义；保留换行符的可读性（日志里偶尔有多行 traceback）
                safe_msg = html_module.escape(message).replace('\n', '<br>&nbsp;&nbsp;&nbsp;&nbsp;')
                safe_name = html_module.escape(name)
                line_html = (
                    f'<span style="color:{color};">'
                    f'[{timestamp}] [{level:<7}] {safe_name}: {safe_msg}'
                    f'</span>'
                )
                cursor.insertHtml(line_html)
                # 用 insertBlock 而不是 <br>，让 setMaximumBlockCount 准确计行
                cursor.insertBlock()
                written += 1

            if self._auto_scroll and written:
                scrollbar = self._view.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
        finally:
            self._view.setUpdatesEnabled(True)

        block_count = self._view.blockCount()
        self._status_label.setText(
            f"显示 {block_count} 行（最多保留 {self.MAX_LINES} 行）"
        )

    # ---- 事件 ----

    def _on_level_toggled(self, level: str, checked: bool):
        if checked:
            self._level_filter.add(level)
            # ERROR 复选框同时控制 CRITICAL（用户视角它们是同一类）
            if level == 'ERROR':
                self._level_filter.add('CRITICAL')
        else:
            self._level_filter.discard(level)
            if level == 'ERROR':
                self._level_filter.discard('CRITICAL')

    def _on_text_filter_changed(self, text: str):
        self._text_filter = text.strip()

    def _on_auto_scroll_toggled(self, checked: bool):
        self._auto_scroll = checked

    def _clear(self):
        self._view.clear()
        self._status_label.setText("已清空")

    def _copy(self):
        text = self._view.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            if self.main_window and hasattr(self.main_window, 'status_bar'):
                self.main_window.status_bar.showMessage("已复制日志到剪贴板", 2000)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", "tools.log",
            "Log Files (*.log);;Text Files (*.txt)"
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(self._view.toPlainText())
            if self.main_window and hasattr(self.main_window, 'status_bar'):
                self.main_window.status_bar.showMessage(f"日志已保存到 {path}", 3000)
        except OSError as e:
            QMessageBox.critical(self, "保存失败", str(e))

    # ---- 生命周期 ----

    def cleanup(self):
        # 关窗时调用：停止 timer、断开 bus 信号
        # 重要：必须在 worker 线程结束前完成，避免它们的 logger.xxx() 调用
        # 经过 bus 转发到已销毁 QObject 的 slot
        if self._cleaned_up:
            return
        self._cleaned_up = True
        try:
            self._flush_timer.stop()
        except Exception:
            pass
        try:
            self._bus.record_emitted.disconnect(self._on_log_record)
        except (TypeError, RuntimeError):
            pass
        # 丢弃任何尚未刷新的记录，防止 _flush 之后被再次调用
        self._pending.clear()
