# 域名提取标签页

import re
from urllib.parse import urlparse, urlunparse
import tldextract

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QLineEdit, QPushButton, QCheckBox, QApplication
)


class DomainExtractorTab(QWidget):
    # 域名/URL提取工具标签页

    _MAX_INPUT_CHARS = 500_000  # 输入上限 50 万字符，防止正则回溯卡死 UI

    _URL_PATTERN = re.compile(
        r'((?:(?:https?|ftp)://)?(?:[a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)+)(?::\d+)?(?:/[^\s"\'<>]*)?)',
        re.IGNORECASE
    )

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        # 禁用在线 PSL 拉取，避免首次运行卡顿/联网；复用 extractor 避免重复初始化开销
        self._tld_extractor = tldextract.TLDExtract(suffix_list_urls=None)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 输入区域
        self.domain_input_label = QLabel("输入文本 (输入行数: 0)：")
        layout.addWidget(self.domain_input_label)
        
        self.domain_input = QTextEdit()
        self.domain_input.setPlaceholderText(
            "粘贴包含URL/域名的文本，每行或混排均可\n支持提取 http/https 链接或裸域名/子域名"
        )
        layout.addWidget(self.domain_input)

        # 选项区域
        opts_layout = QHBoxLayout()
        self.domain_keep_path = QCheckBox("保留路径")
        self.domain_keep_path.setToolTip("勾选后输出完整URL（含路径、参数），否则仅域名")
        self.domain_keep_path.setChecked(False)

        self.domain_dedup = QCheckBox("自动去重")
        self.domain_dedup.setChecked(True)

        self.domain_lower = QCheckBox("小写输出")
        self.domain_lower.setChecked(True)

        opts_layout.addWidget(self.domain_keep_path)
        opts_layout.addWidget(self.domain_dedup)
        opts_layout.addWidget(self.domain_lower)
        opts_layout.addStretch()
        layout.addLayout(opts_layout)

        # 过滤设置
        filt_layout = QHBoxLayout()
        filt_layout.addWidget(QLabel("排除包含："))
        self.domain_exclude_edit = QLineEdit()
        self.domain_exclude_edit.setPlaceholderText("多个关键词用逗号分隔，如: .png,.css,example.com")
        filt_layout.addWidget(self.domain_exclude_edit)
        layout.addLayout(filt_layout)

        # 按钮
        btn_layout = QHBoxLayout()
        self.btn_domain_extract = QPushButton("开始提取")
        self.btn_domain_copy = QPushButton("复制结果")
        self.btn_domain_clear = QPushButton("清空")
        btn_layout.addWidget(self.btn_domain_extract)
        btn_layout.addWidget(self.btn_domain_copy)
        btn_layout.addWidget(self.btn_domain_clear)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 结果区域
        self.domain_output_label = QLabel("提取结果 (提取数量: 0)：")
        layout.addWidget(self.domain_output_label)
        
        self.domain_output = QTextEdit()
        self.domain_output.setReadOnly(True)
        layout.addWidget(self.domain_output)

        # 事件绑定
        self.btn_domain_extract.clicked.connect(self.extract_domains)
        self.btn_domain_copy.clicked.connect(self.copy_domain_output)
        self.btn_domain_clear.clicked.connect(self.clear_domain_fields)
        self.domain_input.textChanged.connect(self.update_domain_counts)

    def extract_domains(self):
        # 提取域名/URL
        text = self.domain_input.toPlainText()
        if not text.strip():
            self.main_window.status_bar.showMessage("请输入包含URL/域名的文本", 2000)
            return
        if len(text) > self._MAX_INPUT_CHARS:
            self.main_window.status_bar.showMessage(f"输入过长（{len(text)} 字符），上限 {self._MAX_INPUT_CHARS}", 3000)
            return

        # 统计输入行数
        input_lines = [line for line in text.splitlines() if line.strip()]
        input_count = len(input_lines)

        exclude_tokens = [t.strip().lower() for t in self.domain_exclude_edit.text().split(',') if t.strip()]

        # 匹配 URL 或域名（支持端口和多种协议）
        matches = list(self._URL_PATTERN.finditer(text))

        results = []
        seen = set()

        for match in matches:
            raw = match.group(0).strip()
            if not raw:
                continue

            # 如果匹配起点前有单个 '/'（而不是 '//'），很可能是路径片段，跳过
            if match.start() > 0:
                prev_char = text[match.start() - 1]
                prev_two = text[match.start() - 2:match.start()] if match.start() >= 2 else ''
                if prev_char == '/' and prev_two != '//':
                    continue

            # 预处理：补协议便于解析
            to_parse = raw if raw.lower().startswith(('http://', 'https://', 'ftp://')) else f"http://{raw}"
            parsed = urlparse(to_parse)
            # 优先使用 hostname，避免把路径误当域名
            host = parsed.hostname
            if not host:
                # 回退用正则从原始串抓域名
                dom_match = re.search(r'([a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)+)', raw)
                host = dom_match.group(1) if dom_match else ''
            if not host:
                continue

            # 使用 tldextract 提取主域名
            ext = self._tld_extractor(host)
            main_domain = ext.registered_domain  # 主域名（如 txzp.com.cn）
            
            if not main_domain:
                continue

            # 是否保留路径
            if self.domain_keep_path.isChecked():
                # 用 urlparse 精确替换 hostname，避免路径中的同名子串被误替换
                if host in raw:
                    scheme_for_parse = raw if '://' in raw else f'http://{raw}'
                    p = urlparse(scheme_for_parse)
                    new_netloc = p.netloc.replace(host, main_domain, 1)
                    rebuilt = urlunparse(p._replace(netloc=new_netloc))
                    # 如果原始输入没有 scheme，去掉拼上去的 http://
                    output = rebuilt[7:] if '://' not in raw else rebuilt
                else:
                    output = raw
            else:
                output = main_domain  # 仅输出主域名

            # 去掉末尾常见标点
            output = output.rstrip('.,;:!?)]}\'"，。；：！？、》）】「」『』【】〈〉《》')

            if self.domain_lower.isChecked():
                output = output.lower()

            # 过滤关键词
            output_cmp = output.lower()
            if exclude_tokens and any(tok in output_cmp for tok in exclude_tokens):
                continue

            # 去重
            key = output
            if self.domain_dedup.isChecked():
                if key in seen:
                    continue
                seen.add(key)

            results.append(output)

        self.domain_output.setPlainText("\n".join(results))
        self.domain_output_label.setText(f"提取结果 (提取数量: {len(results)})：")
        self.main_window.status_bar.showMessage(f"提取完成：{len(results)}/{input_count}", 2000)

    def copy_domain_output(self):
        # 复制提取结果
        text = self.domain_output.toPlainText().strip()
        if not text:
            self.main_window.status_bar.showMessage("没有可复制的结果", 1500)
            return
        QApplication.clipboard().setText(text)
        self.main_window.status_bar.showMessage("已复制提取结果", 2000)

    def clear_domain_fields(self):
        # 清空所有字段
        self.domain_input.clear()
        self.domain_output.clear()
        self.domain_exclude_edit.clear()
        self.domain_output_label.setText("提取结果 (提取数量: 0)：")
        self.update_domain_counts()

    def update_domain_counts(self):
        # 更新行数统计
        in_lines = [line for line in self.domain_input.toPlainText().splitlines() if line.strip()]
        self.domain_input_label.setText(f"输入文本 (输入行数: {len(in_lines)})：")
        out_lines = [line for line in self.domain_output.toPlainText().splitlines() if line.strip()]
        self.domain_output_label.setText(f"提取结果 (提取数量: {len(out_lines)})：")
