# URL工具模块单元测试

import unittest
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.url_utils import normalize_url, is_port_dangerous, DANGEROUS_PORTS, url_sort_key


class TestNormalizeUrl(unittest.TestCase):
    """测试URL规范化功能"""

    def test_simple_domain(self):
        """测试简单域名"""
        result = normalize_url("example.com")
        self.assertIn("https://example.com", result)
        self.assertIn("http://example.com", result)

    def test_with_http_scheme(self):
        """测试带http协议的URL"""
        result = normalize_url("http://example.com")
        self.assertEqual(result, ["http://example.com"])

    def test_with_https_scheme(self):
        """测试带https协议的URL"""
        result = normalize_url("https://example.com")
        self.assertEqual(result, ["https://example.com"])

    def test_with_uppercase_scheme(self):
        """测试大写协议也应被识别为已带 scheme"""
        result = normalize_url("HTTP://example.com")
        self.assertEqual(result, ["HTTP://example.com"])

    def test_with_unsupported_scheme_ftp(self):
        """测试非 http/https 协议应返回明确错误"""
        result = normalize_url("ftp://example.com")
        self.assertEqual(result, ["ftp://example.com [不支持的协议: ftp]"])

    def test_with_unsupported_scheme_mailto(self):
        """测试 mailto 协议应返回明确错误"""
        result = normalize_url("mailto:test@example.com")
        self.assertEqual(result, ["mailto:test@example.com [不支持的协议: mailto]"])

    def test_with_port(self):
        """测试带端口的URL"""
        result = normalize_url("example.com:8080")
        self.assertTrue(any("8080" in url for url in result))

    def test_with_path(self):
        """测试带路径的URL"""
        result = normalize_url("example.com/path/to/page")
        self.assertTrue(any("/path/to/page" in url for url in result))

    def test_empty_input(self):
        """测试空输入"""
        result = normalize_url("")
        # 空输入返回错误标记
        self.assertTrue(len(result) > 0)
        self.assertTrue(any('[' in url for url in result))

    def test_whitespace_input(self):
        """测试空白输入"""
        result = normalize_url("   ")
        # 空白输入返回错误标记
        self.assertTrue(len(result) > 0)
        self.assertTrue(any('[' in url for url in result))

    def test_ip_address(self):
        """测试IP地址"""
        result = normalize_url("192.168.1.1")
        self.assertTrue(len(result) > 0)

    def test_ip_with_port(self):
        """测试IP地址带端口"""
        result = normalize_url("192.168.1.1:8080")
        self.assertTrue(any("8080" in url for url in result))


class TestDangerousPorts(unittest.TestCase):
    """测试危险端口检测"""

    def test_ssh_port(self):
        """测试SSH端口"""
        is_dangerous, _ = is_port_dangerous(22)
        self.assertTrue(is_dangerous)

    def test_mysql_port(self):
        """测试MySQL端口"""
        is_dangerous, _ = is_port_dangerous(3306)
        self.assertTrue(is_dangerous)

    def test_redis_port(self):
        """测试Redis端口"""
        is_dangerous, _ = is_port_dangerous(6379)
        self.assertTrue(is_dangerous)

    def test_http_port(self):
        """测试HTTP端口（安全）"""
        is_dangerous, _ = is_port_dangerous(80)
        self.assertFalse(is_dangerous)

    def test_https_port(self):
        """测试HTTPS端口（安全）"""
        is_dangerous, _ = is_port_dangerous(443)
        self.assertFalse(is_dangerous)

    def test_custom_port(self):
        """测试自定义端口（安全）"""
        is_dangerous, _ = is_port_dangerous(8080)
        self.assertFalse(is_dangerous)

    def test_dangerous_ports_list(self):
        """测试危险端口列表包含关键端口"""
        self.assertIn(22, DANGEROUS_PORTS)    # SSH
        self.assertIn(23, DANGEROUS_PORTS)    # Telnet
        self.assertIn(3306, DANGEROUS_PORTS)  # MySQL
        self.assertIn(6379, DANGEROUS_PORTS)  # Redis


class TestUrlSortKey(unittest.TestCase):
    """测试 URL 排序 key 的健壮性"""

    def test_invalid_port_does_not_raise(self):
        """非法端口不应导致排序崩溃"""
        key = url_sort_key("example.com:abc")
        self.assertIsInstance(key, tuple)


if __name__ == '__main__':
    unittest.main()
