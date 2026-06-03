# Cookie工具模块单元测试

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.cookie_utils import validate_cookie, sanitize_cookie


class TestValidateCookie(unittest.TestCase):
    """测试Cookie验证功能"""

    def test_valid_cookie(self):
        """测试有效Cookie"""
        is_valid, cleaned, error = validate_cookie("session=abc123")
        self.assertTrue(is_valid)
        self.assertEqual(cleaned, "session=abc123")
        self.assertEqual(error, "")

    def test_valid_multiple_cookies(self):
        """测试多个Cookie"""
        is_valid, cleaned, error = validate_cookie("a=1; b=2; c=3")
        self.assertTrue(is_valid)

    def test_empty_cookie(self):
        """测试空Cookie"""
        is_valid, cleaned, error = validate_cookie("")
        self.assertTrue(is_valid)
        self.assertEqual(cleaned, "")

    def test_crlf_injection(self):
        """测试CRLF注入防护"""
        is_valid, cleaned, error = validate_cookie("session=abc\r\nSet-Cookie: evil=1")
        self.assertFalse(is_valid)
        self.assertIn("换行符", error)

    def test_null_byte(self):
        """测试NULL字节检测"""
        is_valid, cleaned, error = validate_cookie("session=abc\x00def")
        self.assertFalse(is_valid)

    def test_too_long_cookie(self):
        """测试超长Cookie"""
        long_cookie = "a=" + "x" * 5000
        is_valid, cleaned, error = validate_cookie(long_cookie)
        self.assertFalse(is_valid)
        self.assertIn("过长", error)


class TestSanitizeCookie(unittest.TestCase):
    """测试Cookie清理功能"""

    def test_trim_whitespace(self):
        """测试去除空白"""
        result = sanitize_cookie("  session=abc  ")
        self.assertEqual(result, "session=abc")

    def test_remove_empty_pairs(self):
        """测试移除空键值对"""
        result = sanitize_cookie("a=1; ; b=2")
        self.assertNotIn(";;", result)


if __name__ == '__main__':
    unittest.main()
