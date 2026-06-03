from __future__ import annotations

import random
from typing import TYPE_CHECKING, List

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from utils import read_urls_from_txt, validate_cookie

if TYPE_CHECKING:
    from .url_checker_tab import UrlCheckerTab


class UrlCheckerInputController:
    def __init__(self, tab: "UrlCheckerTab") -> None:
        self.tab = tab

    def on_ua_changed(self, idx: int) -> None:
        tab = self.tab

        tab.ua_custom_edit.setEnabled(tab.ua_combo.itemText(idx) == "自定义")
        self.update_current_ua_label()

    def get_user_agent(self) -> str:
        tab = self.tab

        if tab.ua_combo.currentText() == "自定义":
            return tab.ua_custom_edit.text().strip() or tab.ua_list[0][1]
        return tab.ua_combo.currentData() or tab.ua_list[0][1]

    def update_current_ua_label(self) -> None:
        self.tab.current_ua_label.setText(f"当前 UA: {self.get_user_agent()}")

    def randomize_ua(self) -> None:
        tab = self.tab

        ua = self.generate_random_ua()
        tab.ua_combo.setCurrentIndex(tab._custom_index)
        tab.ua_custom_edit.setText(ua)
        self.update_current_ua_label()
        if tab.main_window and hasattr(tab.main_window, "status_bar"):
            tab.main_window.status_bar.showMessage("已生成随机 UA", 1500)

    def generate_random_ua(self) -> str:
        def rand_ver(major_range, minor_range=(0, 9), build_range=(0, 9999), patch_range=(0, 150)):
            return (
                f"{random.randint(*major_range)}.{random.randint(*minor_range)}."
                f"{random.randint(*build_range)}.{random.randint(*patch_range)}"
            )

        chrome_ver = rand_ver((110, 124))
        safari_ver = f"{random.randint(600, 610)}.{random.randint(1, 50)}"
        os_choices = [
            ("Windows NT 10.0; Win64; x64", f"Chrome/{chrome_ver} Safari/537.36"),
            ("Windows NT 11.0; Win64; x64", f"Chrome/{chrome_ver} Safari/537.36"),
            (
                f"Macintosh; Intel Mac OS X 10_{random.randint(14, 15)}_{random.randint(0, 7)}",
                f"AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{random.randint(15, 17)}.0 Safari/{safari_ver}",
            ),
            ("X11; Ubuntu; Linux x86_64", f"Chrome/{chrome_ver} Safari/537.36"),
            (
                f"Linux; Android {random.randint(10, 13)}.{random.randint(0, 1)}; "
                f"Pixel {random.randint(3, 8)} Build/{random.randint(7000000, 9000000)}",
                f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{chrome_ver} Mobile Safari/537.36",
            ),
            (
                f"iPhone; CPU iPhone OS {random.randint(15, 17)}_{random.randint(0, 6)} like Mac OS X",
                f"AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{random.randint(15, 17)}.0 "
                f"Mobile/15E148 Safari/604.1",
            ),
        ]

        ua_os, ua_tail = random.choice(os_choices)
        return f"Mozilla/5.0 ({ua_os}) {ua_tail}"

    def collect_urls(self) -> List[str]:
        return [line.strip() for line in self.tab.url_textedit.toPlainText().splitlines() if line.strip()]

    def sync_request_options_from_ui(self) -> bool:
        tab = self.tab

        tab._url_check_user_agent = self.get_user_agent() or "Mozilla/5.0"
        raw_cookie = tab.cookie_edit.text().strip() if hasattr(tab, "cookie_edit") else ""
        if not raw_cookie:
            tab._url_check_cookie = ""
            return True

        is_valid, cleaned_cookie, error_msg = validate_cookie(raw_cookie)
        if not is_valid:
            QMessageBox.warning(tab, "Cookie Error", f"Invalid cookie: {error_msg}")
            return False

        tab._url_check_cookie = cleaned_cookie
        return True

    def reset_run_buffers(self) -> None:
        tab = self.tab

        tab._flush_timer.stop()
        tab._pending_results.clear()

    def load_urls(self) -> None:
        tab = self.tab

        file_path, _ = QFileDialog.getOpenFileName(tab, "选择包含URL的文本文件", "", "Text Files (*.txt)")
        if not file_path:
            return

        try:
            urls = read_urls_from_txt(file_path)
            tab.url_textedit.setPlainText("\n".join(urls))
            tab.main_window.status_bar.showMessage(f"已加载 {len(urls)} 条 URL")
        except Exception as exc:
            QMessageBox.critical(tab, "加载失败", str(exc))
