from typing import List, Dict, Any
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QComboBox, QGroupBox, QScrollArea, QWidget,
    QMessageBox, QTableWidget
)


class AdvancedFilterDialog(QDialog):
    # 表格数据筛选的高级筛选对话框
    
    def __init__(self, parent=None, column_names=None, last_conditions=None):
        super().__init__(parent)
        self.setWindowTitle('高级筛选')
        self.column_names = column_names or []
        self.conditions = []
        self.last_conditions = last_conditions or []
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        self.cond_group = QGroupBox('筛选条件')
        group_layout = QVBoxLayout(self.cond_group)

        self._rows_container = QWidget(self.cond_group)
        self.cond_layout = QVBoxLayout(self._rows_container)
        self.cond_layout.setContentsMargins(0, 0, 0, 0)
        self.cond_layout.setSpacing(6)

        scroll = QScrollArea(self.cond_group)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._rows_container)
        scroll.setMinimumHeight(220)
        group_layout.addWidget(scroll)

        layout.addWidget(self.cond_group)
        
        self.add_btn = QPushButton('添加条件')
        self.add_btn.clicked.connect(self.add_condition)
        layout.addWidget(self.add_btn)
        
        btns = QHBoxLayout()
        self.ok_btn = QPushButton('应用')
        self.ok_btn.clicked.connect(self.on_apply_clicked)
        clear_btn = QPushButton('清除筛选')
        clear_btn.clicked.connect(self.clear_filter)
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self.ok_btn)
        btns.addWidget(clear_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)
        
        if not self.column_names:
            self.add_btn.setEnabled(False)
            self.ok_btn.setEnabled(False)
            # 构造期间弹 QMessageBox 会让对话框还没显示就先弹消息，
            # 焦点和层级容易错乱。改为在对话框内插入提示标签即可。
            empty_label = QLabel("当前表格无可筛选字段")
            empty_label.setStyleSheet("color: #999; padding: 12px;")
            self.cond_layout.addWidget(empty_label)
            return

        if self.last_conditions:
            for cond in self.last_conditions:
                self.add_condition(cond)
        else:
            self.add_condition()

    def add_condition(self, preset=None):
        row_widget = QWidget(self._rows_container)
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)

        col_combo = QComboBox(row_widget)
        col_combo.addItems(self.column_names)
        row.addWidget(col_combo)
        
        op_combo = QComboBox(row_widget)
        op_combo.addItems(['包含', '不包含', '等于', '不等于', '开头是', '结尾是', '为空', '不为空'])
        row.addWidget(op_combo)
        
        val_edit = QLineEdit(row_widget)
        row.addWidget(val_edit)
        
        rm_btn = QPushButton('移除', row_widget)
        rm_btn.clicked.connect(lambda: self.remove_condition(row_widget))
        row.addWidget(rm_btn)
        
        op_combo.currentTextChanged.connect(lambda _: self._sync_value_enabled(op_combo, val_edit))

        self.cond_layout.addWidget(row_widget)
        self.conditions.append({'widget': row_widget, 'col': col_combo, 'op': op_combo, 'val': val_edit})
        
        if preset:
            preset_column = preset.get('column')
            col_idx = self.column_names.index(preset_column) if preset_column in self.column_names else 0
            col_combo.setCurrentIndex(col_idx)
            op_idx = op_combo.findText(preset.get('operator', '包含'))
            if op_idx >= 0:
                op_combo.setCurrentIndex(op_idx)
            val_edit.setText(preset.get('value', ''))

        self._sync_value_enabled(op_combo, val_edit)
        self.adjustSize()

    @staticmethod
    def _sync_value_enabled(op_combo: QComboBox, val_edit: QLineEdit) -> None:
        op = op_combo.currentText()
        needs_value = op not in {"为空", "不为空"}
        val_edit.setEnabled(needs_value)
        if not needs_value:
            val_edit.setText("")

    def remove_condition(self, row_widget: QWidget) -> None:
        for i, cond in enumerate(self.conditions):
            if cond['widget'] == row_widget:
                self.cond_layout.removeWidget(row_widget)
                row_widget.deleteLater()
                self.conditions.pop(i)
                self.adjustSize()
                break

    def on_apply_clicked(self) -> None:
        invalid = []
        for idx, cond in enumerate(self.conditions, start=1):
            col = cond["col"].currentText().strip()
            op = cond["op"].currentText().strip()
            val = cond["val"].text().strip()
            if not col:
                invalid.append(f"第{idx}条：字段为空")
                continue
            if op not in {"为空", "不为空"} and not val:
                invalid.append(f"第{idx}条：筛选值为空")

        if invalid:
            QMessageBox.warning(self, "条件不完整", "请完善筛选条件后再应用：\n" + "\n".join(invalid))
            return

        self.accept()

    def get_conditions(self):
        result = []
        for cond in self.conditions:
            col = cond['col'].currentText().strip()
            if not col:
                continue

            op = cond['op'].currentText().strip()
            val = cond['val'].text().strip()
            result.append({
                'column': col,
                'operator': op,
                'value': val
            })
        return result

    def clear_filter(self):
        for cond in self.conditions:
            w = cond.get("widget")
            if isinstance(w, QWidget):
                self.cond_layout.removeWidget(w)
                w.deleteLater()
        self.conditions.clear()
        self.adjustSize()
        self.accept()

    @staticmethod
    def apply_filter_to_table(table: QTableWidget, conditions: List[Dict[str, Any]]) -> None:
        # 应用筛选条件到表格（静态方法，可被多处复用）
        header_to_idx: Dict[str, int] = {}
        for i in range(table.columnCount()):
            header_item = table.horizontalHeaderItem(i)
            if header_item:
                header_to_idx[header_item.text()] = i

        for row in range(table.rowCount()):
            row_hidden = False
            for cond in conditions:
                col_name = str(cond.get("column", "")).strip()
                op = str(cond.get("operator", "包含")).strip()
                raw_val = str(cond.get("value", "")).strip()

                col_idx = header_to_idx.get(col_name, -1)
                if col_idx == -1:
                    row_hidden = True
                    break

                item = table.item(row, col_idx)
                text_raw = item.text() if item else ""
                text = text_raw.lower()

                if op == "为空":
                    if text_raw.strip() != "":
                        row_hidden = True
                        break
                    continue
                if op == "不为空":
                    if text_raw.strip() == "":
                        row_hidden = True
                        break
                    continue

                if raw_val == "":
                    continue

                val = raw_val.lower()
                if op == "包含":
                    if val not in text:
                        row_hidden = True
                        break
                elif op == "不包含":
                    if val in text:
                        row_hidden = True
                        break
                elif op == "等于":
                    if val != text:
                        row_hidden = True
                        break
                elif op == "不等于":
                    if val == text:
                        row_hidden = True
                        break
                elif op == "开头是":
                    if not text.startswith(val):
                        row_hidden = True
                        break
                elif op == "结尾是":
                    if not text.endswith(val):
                        row_hidden = True
                        break
            table.setRowHidden(row, row_hidden)

