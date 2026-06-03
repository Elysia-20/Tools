# URL工具标签页

from typing import List

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, QApplication
)

from utils import url_sort_key


class UrlToolsTab(QWidget):
    """URL工具：批量去重/排序"""

    _MAX_INPUT_CHARS = 1_000_000  # 输入上限 100 万字符

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 输入区域
        self.url_tools_input_label = QLabel("输入列表 (输入行数: 0)：")
        layout.addWidget(self.url_tools_input_label)
        
        self.url_tools_input = QTextEdit()
        self.url_tools_input.setPlaceholderText(
            "每行一个URL或域名，可包含端口/path\n例如:\nhttps://example.com\nfoo.test:8080\nhttp://demo.local/login"
        )
        layout.addWidget(self.url_tools_input)

        # 按钮区域
        btn_layout = QHBoxLayout()
        self.btn_tools_dedup = QPushButton("去重")
        self.btn_tools_sort = QPushButton("排序 (A→Z)")
        self.btn_tools_dedup_sort = QPushButton("去重并排序")
        self.btn_tools_clear = QPushButton("清空")
        btn_layout.addWidget(self.btn_tools_dedup)
        btn_layout.addWidget(self.btn_tools_sort)
        btn_layout.addWidget(self.btn_tools_dedup_sort)
        btn_layout.addWidget(self.btn_tools_clear)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 结果区域
        self.url_tools_output_label = QLabel("结果 (结果行数: 0)：")
        layout.addWidget(self.url_tools_output_label)
        
        self.url_tools_output = QTextEdit()
        self.url_tools_output.setReadOnly(True)
        layout.addWidget(self.url_tools_output)

        # 复制按钮
        copy_layout = QHBoxLayout()
        self.btn_tools_copy = QPushButton("复制结果")
        copy_layout.addWidget(self.btn_tools_copy)
        copy_layout.addStretch()
        layout.addLayout(copy_layout)

        # 事件绑定
        self.btn_tools_dedup.clicked.connect(self.dedup_urls_only)
        self.btn_tools_sort.clicked.connect(self.sort_urls_only)
        self.btn_tools_dedup_sort.clicked.connect(self.dedup_and_sort_urls)
        self.btn_tools_clear.clicked.connect(self.clear_url_tools)
        self.btn_tools_copy.clicked.connect(self.copy_url_tools_output)
        self.url_tools_input.textChanged.connect(self.update_url_tools_counts)

    def _get_url_tools_input(self) -> List[str]:
        """获取输入的URL列表"""
        text = self.url_tools_input.toPlainText()
        if len(text) > self._MAX_INPUT_CHARS:
            self.main_window.status_bar.showMessage(
                f"输入过长（{len(text)} 字符），上限 {self._MAX_INPUT_CHARS}", 3000
            )
            return []
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _set_url_tools_output(self, lines: List[str], message: str) -> None:
        """设置输出结果并显示消息"""
        self.url_tools_output.setPlainText("\n".join(lines))
        self.main_window.status_bar.showMessage(message, 2500)
        self.update_url_tools_counts()

    def _dedup_urls(self, urls: List[str]) -> List[str]:
        """大小写不敏感去重，保留首次出现的原始大小写"""
        seen = set()
        unique = []
        for u in urls:
            key = u.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(u)
        return unique

    def dedup_urls_only(self):
        """仅去重"""
        urls = self._get_url_tools_input()
        if not urls:
            self.main_window.status_bar.showMessage("请输入要去重的URL", 2000)
            return
        unique = self._dedup_urls(urls)
        self._set_url_tools_output(unique, f"去重完成：{len(unique)}/{len(urls)}")

    def sort_urls_only(self):
        """仅排序"""
        urls = self._get_url_tools_input()
        if not urls:
            self.main_window.status_bar.showMessage("请输入要排序的URL", 2000)
            return
        sorted_urls = sorted(urls, key=url_sort_key)
        self._set_url_tools_output(sorted_urls, f"排序完成：{len(sorted_urls)} 行")

    def dedup_and_sort_urls(self):
        """去重并排序"""
        urls = self._get_url_tools_input()
        if not urls:
            self.main_window.status_bar.showMessage("请输入要处理的URL", 2000)
            return
        unique = self._dedup_urls(urls)
        sorted_unique = sorted(unique, key=url_sort_key)
        self._set_url_tools_output(sorted_unique, f"去重并排序完成：{len(sorted_unique)}/{len(urls)}")

    def clear_url_tools(self):
        """清空输入和输出"""
        self.url_tools_input.clear()
        self.url_tools_output.clear()
        self.main_window.status_bar.showMessage("已清空URL工具输入/结果", 1500)
        self.update_url_tools_counts()

    def copy_url_tools_output(self):
        """复制结果到剪贴板"""
        text = self.url_tools_output.toPlainText().strip()
        if not text:
            self.main_window.status_bar.showMessage("没有可复制的结果", 1500)
            return
        QApplication.clipboard().setText(text)
        self.main_window.status_bar.showMessage("已复制结果到剪贴板", 2000)

    def update_url_tools_counts(self):
        """更新行数统计"""
        in_count = len(self._get_url_tools_input())
        out_lines = [line for line in self.url_tools_output.toPlainText().splitlines() if line.strip()]
        out_count = len(out_lines)
        self.url_tools_input_label.setText(f"输入列表 (输入行数: {in_count})：")
        self.url_tools_output_label.setText(f"结果 (结果行数: {out_count})：")
