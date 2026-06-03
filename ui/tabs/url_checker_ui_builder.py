from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from .url_checker_tab import UrlCheckerTab


class UrlCheckerUiBuilder:
    def __init__(self, tab: "UrlCheckerTab") -> None:
        self.tab = tab

    def build(self) -> None:
        tab = self.tab

        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)

        main_layout.addWidget(self._build_config_group())
        main_layout.addWidget(self._build_result_table(), 1)

        self._connect_signals()
        tab.update_current_ua_label()

    def _build_config_group(self) -> QGroupBox:
        tab = self.tab

        config_group = QGroupBox("URL输入配置")
        config_layout = QVBoxLayout(config_group)
        config_layout.setContentsMargins(6, 6, 6, 6)
        config_layout.setSpacing(4)

        tab.url_textedit = QTextEdit()
        tab.url_textedit.setPlaceholderText(
            "每行一个 URL，支持 http/https 或裸域名\n例如: example.com  |  https://test.com"
        )
        tab.url_textedit.setMaximumHeight(100)
        config_layout.addWidget(tab.url_textedit)

        config_layout.addLayout(self._build_request_options_row())
        config_layout.addWidget(self._build_current_ua_label())
        config_layout.addLayout(self._build_action_row())
        config_layout.addLayout(self._build_check_options_row())
        return config_group

    def _build_request_options_row(self) -> QHBoxLayout:
        tab = self.tab

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("UA:"))

        tab.ua_combo = QComboBox()
        tab.ua_list = [
            (
                "Chrome",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            ),
            (
                "Edge",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
            ),
            (
                "Firefox",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
            ),
            (
                "Safari",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            ),
            (
                "手机-微信",
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
                "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.0(0x18000021) "
                "NetType/WIFI Language/zh_CN",
            ),
            ("自定义", ""),
        ]
        for name, ua in tab.ua_list:
            tab.ua_combo.addItem(name, ua)
        tab._custom_index = next(i for i, (name, _) in enumerate(tab.ua_list) if name == "自定义")
        row.addWidget(tab.ua_combo)

        tab.ua_random_btn = QPushButton("随机")
        tab.ua_random_btn.setToolTip("从预置列表随机选择一个常见浏览器 UA")
        tab.ua_random_btn.setFixedWidth(40)
        row.addWidget(tab.ua_random_btn)

        tab.ua_custom_edit = QLineEdit()
        tab.ua_custom_edit.setPlaceholderText("自定义 UA")
        tab.ua_custom_edit.setEnabled(False)
        row.addWidget(tab.ua_custom_edit, 1)

        row.addWidget(QLabel("Cookie:"))
        tab.cookie_edit = QLineEdit()
        tab.cookie_edit.setPlaceholderText("可选: key1=value1; key2=value2")
        row.addWidget(tab.cookie_edit, 1)
        return row

    def _build_current_ua_label(self) -> QLabel:
        tab = self.tab

        tab.current_ua_label = QLabel()
        tab.current_ua_label.setWordWrap(True)
        tab.current_ua_label.setStyleSheet("color: #555;")
        return tab.current_ua_label

    def _build_action_row(self) -> QHBoxLayout:
        tab = self.tab

        row = QHBoxLayout()
        row.setSpacing(6)

        tab.btn_load_urls = QPushButton("加载文件")
        tab.btn_check_urls = QPushButton("开始检查")
        tab.btn_stop_urls = QPushButton("停止")
        tab.btn_retry_failed = QPushButton("重试失败")
        tab.btn_clear_urls = QPushButton("清空")
        tab.btn_export_urls = QPushButton("导出")
        tab.btn_advanced_filter = QPushButton("高级筛选")

        for button in [
            tab.btn_load_urls,
            tab.btn_check_urls,
            tab.btn_stop_urls,
            tab.btn_retry_failed,
            tab.btn_clear_urls,
            tab.btn_export_urls,
            tab.btn_advanced_filter,
        ]:
            row.addWidget(button)

        row.addWidget(QLabel("线程:"))
        tab.thread_spin = QSpinBox()
        tab.thread_spin.setRange(1, 20)
        tab.thread_spin.setValue(5)
        tab.thread_spin.setFixedWidth(50)
        row.addWidget(tab.thread_spin)

        row.addStretch()
        return row

    def _build_check_options_row(self) -> QHBoxLayout:
        tab = self.tab

        row = QHBoxLayout()
        row.setSpacing(10)

        tab.ssl_verify_checkbox = QCheckBox("验证 SSL")
        tab.ssl_verify_checkbox.setChecked(True)
        tab.ssl_verify_checkbox.setToolTip("验证 SSL 证书 (推荐)")

        tab.https_downgrade_checkbox = QCheckBox("HTTPS 降级")
        tab.https_downgrade_checkbox.setChecked(False)
        tab.https_downgrade_checkbox.setToolTip("仅在 HTTPS 连接或握手失败时额外尝试一次 HTTP")

        tab.allow_internal_checkbox = QCheckBox("允许内网")
        tab.allow_internal_checkbox.setChecked(False)
        tab.allow_internal_checkbox.setToolTip("开启后将允许访问内网与本机地址，请确保在授权范围内使用")

        tab.full_length_checkbox = QCheckBox("完整 Length")
        tab.full_length_checkbox.setChecked(False)
        tab.full_length_checkbox.setToolTip(
            "当服务器未返回 Content-Length 时，读取完整响应体计算大小，可能变慢"
        )

        tab.follow_meta_refresh_checkbox = QCheckBox("跟随 Meta Refresh")
        tab.follow_meta_refresh_checkbox.setChecked(False)
        tab.follow_meta_refresh_checkbox.setToolTip("跟随 meta refresh 跳转以获取真实标题与指纹，可能变慢")

        for checkbox in [
            tab.ssl_verify_checkbox,
            tab.https_downgrade_checkbox,
            tab.allow_internal_checkbox,
            tab.full_length_checkbox,
            tab.follow_meta_refresh_checkbox,
        ]:
            row.addWidget(checkbox)

        row.addStretch()
        return row

    def _build_result_table(self) -> QTableWidget:
        tab = self.tab

        tab.url_table = QTableWidget(0, 8)
        tab.url_table.setHorizontalHeaderLabels(
            ["原始 URL", "实际访问 URL", "IP", "Status", "Title", "Banner", "Length", "异常信息"]
        )
        tab.url_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        tab.url_table.horizontalHeader().setSectionResizeMode(
            0, tab.url_table.horizontalHeader().ResizeMode.ResizeToContents
        )
        tab.url_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), tab.url_table)
        copy_shortcut.activated.connect(lambda: tab.main_window.copy_table_selection(tab.url_table))
        return tab.url_table

    def _connect_signals(self) -> None:
        tab = self.tab

        tab.ua_combo.currentIndexChanged.connect(tab.on_ua_changed)
        tab.ua_random_btn.clicked.connect(tab.randomize_ua)
        tab.ua_custom_edit.textChanged.connect(tab.update_current_ua_label)

        tab.url_table.customContextMenuRequested.connect(tab.show_context_menu)
        tab.url_table.horizontalHeader().sectionDoubleClicked.connect(tab.auto_resize_column)

        tab.btn_load_urls.clicked.connect(tab.load_urls)
        tab.btn_check_urls.clicked.connect(tab.start_check)
        tab.btn_stop_urls.clicked.connect(tab.stop_check)
        tab.btn_retry_failed.clicked.connect(tab.retry_failed)
        tab.btn_clear_urls.clicked.connect(tab.clear_all)
        tab.btn_export_urls.clicked.connect(tab.export_results)
        tab.btn_advanced_filter.clicked.connect(tab.open_advanced_filter_dialog)
