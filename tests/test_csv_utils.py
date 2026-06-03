# CSV工具模块单元测试

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.csv_utils import escape_csv_cell


class TestEscapeCsvCell(unittest.TestCase):
    """测试CSV单元格转义功能（防止公式注入）"""

    def test_normal_text(self):
        """测试普通文本"""
        self.assertEqual(escape_csv_cell("hello"), "hello")

    def test_equals_prefix(self):
        """测试等号前缀（公式注入）"""
        self.assertEqual(escape_csv_cell("=SUM(A1:A10)"), "'=SUM(A1:A10)")

    def test_plus_prefix(self):
        """测试加号前缀"""
        self.assertEqual(escape_csv_cell("+1234"), "'+1234")

    def test_minus_prefix(self):
        """测试减号前缀"""
        self.assertEqual(escape_csv_cell("-1234"), "'-1234")

    def test_at_prefix(self):
        """测试@前缀"""
        self.assertEqual(escape_csv_cell("@SUM(A1)"), "'@SUM(A1)")

    def test_none_value(self):
        """测试None值"""
        self.assertEqual(escape_csv_cell(None), "")

    def test_number(self):
        """测试数字"""
        self.assertEqual(escape_csv_cell(123), "123")

    def test_whitespace_before_dangerous(self):
        """测试危险字符前有空白"""
        self.assertEqual(escape_csv_cell("  =formula"), "'  =formula")

    def test_safe_text_with_equals(self):
        """测试中间包含等号的安全文本"""
        self.assertEqual(escape_csv_cell("a=b"), "a=b")


if __name__ == '__main__':
    unittest.main()
