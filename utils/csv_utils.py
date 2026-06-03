# CSV 导出安全工具
#
# 主要防护：CSV/Excel 公式注入（CSV Injection）

from __future__ import annotations


_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "|")


def escape_csv_cell(value: object) -> str:
    """
    将单元格内容转换为对 Excel 更安全的文本，避免以公式形式被执行。

    规则：如果内容去掉前导空白后的首字符为 = + - @ |，则在原字符串前追加单引号。
    注意：不在此处理嵌入的 CRLF/引号——所有调用方都使用 csv.writer，
    由其负责字段引用。本函数只负责防 Excel/CSV 公式注入。
    """
    if value is None:
        return ""

    text = str(value)
    stripped = text.lstrip(" \t\r\n")
    if stripped and stripped[0] in _DANGEROUS_PREFIXES:
        return "'" + text
    return text

