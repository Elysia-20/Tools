# 正则缓存模块单元测试

import unittest
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.regex_cache import RegexCache


class TestRegexCache(unittest.TestCase):
    """测试正则表达式缓存功能"""

    def test_get_html_tags_regex(self):
        """测试获取html_tags正则"""
        pattern = RegexCache.get('html_tags')
        self.assertIsNotNone(pattern)
        self.assertIsInstance(pattern, re.Pattern)

    def test_html_tags_regex_matches(self):
        """测试html_tags正则匹配"""
        pattern = RegexCache.get('html_tags')
        result = pattern.sub('', "<b>Hello</b> <i>World</i>")
        self.assertEqual(result, "Hello World")

    def test_get_chinese_regex(self):
        """测试获取中文检测正则"""
        pattern = RegexCache.get('chinese')
        self.assertIsNotNone(pattern)

    def test_chinese_regex_matches(self):
        """测试中文正则匹配"""
        pattern = RegexCache.get('chinese')
        self.assertIsNotNone(pattern.search("你好世界"))
        self.assertIsNone(pattern.search("hello world"))

    def test_cache_returns_same_instance(self):
        """测试缓存返回相同实例"""
        pattern1 = RegexCache.get('chinese')
        pattern2 = RegexCache.get('chinese')
        self.assertIs(pattern1, pattern2)

    def test_invalid_key(self):
        """测试无效键"""
        with self.assertRaises(KeyError):
            RegexCache.get('nonexistent_key')


if __name__ == '__main__':
    unittest.main()
