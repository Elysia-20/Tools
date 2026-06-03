from __future__ import annotations

import csv
import webbrowser
from typing import TYPE_CHECKING, Any, Dict, List

from PyQt6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox
from PyQt6.QtGui import QAction

from utils import escape_csv_cell
from workers.url_worker import sanitize_url_for_export
from ..dialogs import AdvancedFilterDialog

if TYPE_CHECKING:
    from .url_checker_tab import UrlCheckerTab


class UrlCheckerTableController:
    def __init__(self, tab: "UrlCheckerTab") -> None:
        self.tab = tab

    def export_results(self) -> None:
        tab = self.tab

        if tab.url_table.rowCount() == 0:
            QMessageBox.warning(tab, "提示", "没有可导出的URL检查结果")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            tab,
            "导出URL检查结果",
            "url_check_results.csv",
            "CSV Files (*.csv)",
        )
        if not file_path:
            return

        from workers.url_worker import sanitize_url_for_export

        try:
            with open(file_path, "w", encoding="utf-8-sig", newline="") as file_obj:
                writer = csv.writer(file_obj)
                writer.writerow(["original_url", "final_url", "ip", "status", "title", "banner", "length", "error"])
                for row in range(tab.url_table.rowCount()):
                    values = []
                    for col in range(tab.url_table.columnCount()):
                        item = tab.url_table.item(row, col)
                        values.append(item.text() if item else "")
                    if values:
                        values[0] = sanitize_url_for_export(values[0])
                        values[1] = sanitize_url_for_export(values[1]) if len(values) > 1 else ""
                        if len(values) > 7:
                            values[7] = sanitize_url_for_export(values[7])
                    writer.writerow([escape_csv_cell(value) for value in values])
            tab.main_window.status_bar.showMessage(f"URL检查结果已导出到 {file_path}")
        except Exception as exc:
            QMessageBox.critical(tab, "导出错误", f"导出失败：{exc}")

    def show_context_menu(self, pos) -> None:
        tab = self.tab

        menu = QMenu(tab)
        menu.setStyleSheet("QMenu { text-align: left; }")

        item = tab.url_table.itemAt(pos)
        if item:
            row = item.row()
            url_item = tab.url_table.item(row, 1) or tab.url_table.item(row, 0)
            if url_item:
                url = url_item.text()
                open_action = QAction(f"打开 {url[:50]}{'...' if len(url) > 50 else ''}", tab)
                open_action.triggered.connect(lambda _=False, u=url: self.open_url(u))
                menu.addAction(open_action)
                menu.addSeparator()

            copy_action = QAction(
                f"复制: {item.text()[:30]}{'...' if len(item.text()) > 30 else ''}",
                tab,
            )
            copy_action.triggered.connect(lambda _=False, text=item.text(): QApplication.clipboard().setText(text))
            menu.addAction(copy_action)

        auto_all = QAction("自动调整所有列宽", tab)
        auto_all.triggered.connect(self.auto_resize_all_columns)
        menu.addAction(auto_all)

        filter_action = QAction("高级筛选", tab)
        filter_action.triggered.connect(self.open_advanced_filter_dialog)
        menu.addAction(filter_action)

        menu.exec(tab.url_table.mapToGlobal(pos))

    def auto_resize_all_columns(self) -> None:
        self.tab.url_table.resizeColumnsToContents()

    def auto_resize_column(self, logical_index: int) -> None:
        self.tab.url_table.resizeColumnToContents(logical_index)

    def open_url(self, url: str) -> None:
        if not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        webbrowser.open(url)

    def open_advanced_filter_dialog(self) -> None:
        tab = self.tab

        if tab.url_table.rowCount() == 0:
            QMessageBox.information(tab, "提示", "暂无数据可筛选")
            return

        column_names = [
            tab.url_table.horizontalHeaderItem(i).text()
            for i in range(tab.url_table.columnCount())
        ]
        dialog = AdvancedFilterDialog(tab, column_names, last_conditions=tab._last_filter_conditions)
        dialog.setModal(True)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        conditions = dialog.get_conditions()
        if not conditions:
            self.clear_advanced_filter()
            return

        tab._last_filter_conditions = conditions
        self.advanced_filter_table(conditions)

    def advanced_filter_table(self, conditions: List[Dict[str, Any]]) -> None:
        AdvancedFilterDialog.apply_filter_to_table(self.tab.url_table, conditions)

    def clear_advanced_filter(self) -> None:
        tab = self.tab

        for row in range(tab.url_table.rowCount()):
            tab.url_table.setRowHidden(row, False)
        tab._last_filter_conditions = []
