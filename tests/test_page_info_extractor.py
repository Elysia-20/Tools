import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.page_info_extractor import (
    HtmlHeadParser,
    decode_html_intelligently,
    extract_banner,
    extract_page_info,
    extract_title,
    parse_html,
)


class TestPageInfoExtractor(unittest.TestCase):
    def test_parse_html_returns_parser_on_bad_input(self):
        parser = parse_html(None)  # type: ignore[arg-type]
        self.assertIsInstance(parser, HtmlHeadParser)

    def test_decode_html_intelligently_handles_utf8_bytes(self):
        decoded = decode_html_intelligently('你好'.encode('utf-8'))
        self.assertEqual(decoded, '你好')

    def test_extract_title_uses_meta_and_content_type_fallbacks(self):
        html = '<meta property="og:title" content="OG Title">'
        self.assertEqual(extract_title(html), 'OG Title')
        self.assertEqual(
            extract_title('', response_headers={'Content-Type': 'application/json'}),
            '[JSON API 接口]',
        )

    def test_extract_banner_detects_headers_and_frameworks(self):
        html = '<script src="/wp-content/themes/main.js"></script>'
        banner = extract_banner(html, response_headers={'Server': 'nginx/1.20'})
        self.assertIn('Server: nginx/1.20', banner)
        self.assertIn('WordPress', banner)

    def test_extract_page_info_combines_title_and_banner(self):
        title, banner = extract_page_info(
            '<html><head><title>Hello</title><meta name="generator" content="Drupal 10"></head></html>'
        )
        self.assertEqual(title, 'Hello')
        self.assertIn('Drupal 10', banner)


if __name__ == '__main__':
    unittest.main()
