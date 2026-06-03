import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.url_safety import is_safe_ip, is_safe_url, validate_ip_object


class TestUrlSafety(unittest.TestCase):
    def test_validate_ip_object_blocks_private_without_allow_internal(self):
        import ipaddress

        safe, reason = validate_ip_object(
            ipaddress.ip_address('10.0.0.1'),
            '10.0.0.1',
            allow_internal=False,
        )
        self.assertFalse(safe)
        self.assertIn('内网地址', reason)

    def test_validate_ip_object_allows_private_with_allow_internal(self):
        import ipaddress

        safe, reason = validate_ip_object(
            ipaddress.ip_address('10.0.0.1'),
            '10.0.0.1',
            allow_internal=True,
        )
        self.assertTrue(safe)
        self.assertEqual(reason, '')

    def test_is_safe_ip_rejects_empty_and_unparseable_values(self):
        # 空字符串和非法IP一律拒绝（防止SSRF绕过）
        safe, _ = is_safe_ip('', allow_internal=False)
        self.assertFalse(safe)
        safe, _ = is_safe_ip('not-an-ip', allow_internal=False)
        self.assertFalse(safe)

    def test_is_safe_url_blocks_localhost_and_dangerous_port(self):
        safe, reason = is_safe_url('http://localhost', allow_internal=False)
        self.assertFalse(safe)
        self.assertIn('本地主机', reason)

        safe, reason = is_safe_url(
            'http://example.com:22',
            allow_internal=False,
            dangerous_ports={22: 'SSH'},
        )
        self.assertFalse(safe)
        self.assertIn('危险端口', reason)

    def test_is_safe_url_rejects_invalid_port_without_raising(self):
        safe, reason = is_safe_url('http://example.com:abc', allow_internal=False)
        self.assertFalse(safe)
        self.assertIn('无效端口', reason)

        safe, reason = is_safe_url('http://example.com:0', allow_internal=False)
        self.assertFalse(safe)
        self.assertIn('端口0', reason)

    def test_is_safe_url_allows_regular_public_target(self):
        safe, reason = is_safe_url('https://example.com', allow_internal=False)
        self.assertTrue(safe)
        self.assertEqual(reason, '')


if __name__ == '__main__':
    unittest.main()
