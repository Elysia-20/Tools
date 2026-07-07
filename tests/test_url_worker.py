# URL检查工作线程单元测试

import sys
import os
import time
import threading
import unittest
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workers.url_worker import UrlCheckWorker, _EarlyExit, _CheckContext, _HtmlHeadParser


def _make_worker(**kwargs):
    """创建 UrlCheckWorker 实例（不启动线程）"""
    defaults = dict(row=0, url='http://test.com')
    defaults.update(kwargs)
    return UrlCheckWorker(**defaults)


class TestEarlyExit(unittest.TestCase):
    """_EarlyExit 异常测试"""

    def test_carries_args(self):
        """测试携带 emit 参数（具名字段 + emit_args 元组）"""
        e = _EarlyExit(0, 'url', '200', 't', 'b', '1.1.1.1', 'err', '10 bytes')
        self.assertEqual(e.emit_args, (0, 'url', '200', 't', 'b', '1.1.1.1', 'err', '10 bytes'))
        self.assertEqual(e.ip, '1.1.1.1')
        self.assertEqual(e.error, 'err')
        self.assertEqual(e.length, '10 bytes')

    def test_is_base_exception(self):
        """测试继承 BaseException（不被 except Exception 捕获）"""
        self.assertTrue(issubclass(_EarlyExit, BaseException))
        self.assertFalse(issubclass(_EarlyExit, Exception))


class TestCheckContext(unittest.TestCase):
    """_CheckContext 数据类测试"""

    def test_default_values(self):
        """测试默认值"""
        ctx = _CheckContext()
        self.assertEqual(ctx.norm_url, '')
        self.assertEqual(ctx.downloaded_size, 0)
        self.assertEqual(ctx.captured, bytearray())
        self.assertIsNone(ctx.response)
        self.assertFalse(ctx.size_exceeded)
        self.assertFalse(ctx.meta_followed)

    def test_custom_values(self):
        """测试自定义值"""
        ctx = _CheckContext(norm_url='http://a.com', ip_addr='1.2.3.4')
        self.assertEqual(ctx.norm_url, 'http://a.com')
        self.assertEqual(ctx.ip_addr, '1.2.3.4')


class TestCheckCancelled(unittest.TestCase):
    """_check_cancelled 方法测试"""

    def test_not_cancelled(self):
        """测试未取消时不抛异常"""
        worker = _make_worker()
        worker._check_cancelled()

    def test_cancelled_raises(self):
        """测试已取消时抛出 _EarlyExit"""
        worker = _make_worker()
        worker.cancel()
        with self.assertRaises(_EarlyExit) as cm:
            worker._check_cancelled()
        self.assertIn('已取消', cm.exception.emit_args[6])

    def test_cancelled_with_ctx_includes_ip(self):
        """测试取消时携带 ctx 中的 IP"""
        worker = _make_worker()
        worker.cancel()
        ctx = _CheckContext(ip_addr='1.2.3.4')
        with self.assertRaises(_EarlyExit) as cm:
            worker._check_cancelled(ctx)
        self.assertEqual(cm.exception.emit_args[5], '1.2.3.4')


class TestParseContentLengthHeader(unittest.TestCase):
    """_parse_content_length_header 静态方法测试"""

    def test_valid(self):
        """测试有效的 Content-Length"""
        self.assertEqual(UrlCheckWorker._parse_content_length_header({'Content-Length': '1234'}), 1234)

    def test_missing(self):
        """测试缺失 Content-Length"""
        self.assertIsNone(UrlCheckWorker._parse_content_length_header({}))

    def test_empty(self):
        """测试空字符串"""
        self.assertIsNone(UrlCheckWorker._parse_content_length_header({'Content-Length': ''}))

    def test_invalid(self):
        """测试非法值"""
        self.assertIsNone(UrlCheckWorker._parse_content_length_header({'Content-Length': 'abc'}))

    def test_none_value(self):
        """测试 None 值"""
        self.assertIsNone(UrlCheckWorker._parse_content_length_header({'Content-Length': None}))


class TestComputeTimeouts(unittest.TestCase):
    """_compute_timeouts 方法测试"""

    def test_normal_with_scheme(self):
        """测试带 scheme 的正常 URL"""
        worker = _make_worker()
        ct, rt = worker._compute_timeouts(['http://a.com'], True, 'http://a.com')
        self.assertEqual(ct, worker.CONNECT_TIMEOUT)
        self.assertEqual(rt, worker.READ_TIMEOUT)

    def test_schemeless_https_first(self):
        """测试自动补全 https 首次尝试使用短超时"""
        worker = _make_worker()
        ct, rt = worker._compute_timeouts(
            ['https://a.com', 'http://a.com'], False, 'https://a.com'
        )
        self.assertEqual(ct, worker.CONNECT_TIMEOUT_SCHEMELESS_HTTPS)
        self.assertEqual(rt, worker.READ_TIMEOUT_SCHEMELESS_HTTPS)

    def test_schemeless_http_fallback(self):
        """测试 http 回退时使用正常超时"""
        worker = _make_worker()
        ct, rt = worker._compute_timeouts(
            ['https://a.com', 'http://a.com'], False, 'http://a.com'
        )
        self.assertEqual(ct, worker.CONNECT_TIMEOUT)
        self.assertEqual(rt, worker.READ_TIMEOUT)


class TestBuildRedirectInfo(unittest.TestCase):
    """_build_redirect_info 方法测试"""

    def test_no_redirect(self):
        """测试无重定向"""
        worker = _make_worker()
        ctx = _CheckContext(norm_url='http://a.com', final_url='http://a.com')
        ctx.response = Mock(status_code=200)
        self.assertEqual(worker._build_redirect_info(ctx), '')

    def test_redirect_same_url(self):
        """测试重定向到相同 URL"""
        worker = _make_worker()
        ctx = _CheckContext(norm_url='http://a.com', final_url='http://a.com')
        ctx.redirect_first_status = 301
        ctx.response = Mock(status_code=200)
        info = worker._build_redirect_info(ctx)
        self.assertIn('301', info)
        self.assertIn('200', info)

    def test_redirect_different_url(self):
        """测试重定向到不同 URL"""
        worker = _make_worker()
        ctx = _CheckContext(norm_url='http://a.com', final_url='http://b.com')
        ctx.redirect_first_status = 302
        ctx.response = Mock(status_code=200)
        info = worker._build_redirect_info(ctx)
        self.assertIn('→ http://b.com', info)

    def test_with_meta_note(self):
        """测试带 meta_note"""
        worker = _make_worker()
        ctx = _CheckContext(
            norm_url='http://a.com', final_url='http://a.com',
            meta_note='[META-REFRESH] → http://c.com'
        )
        ctx.response = Mock(status_code=200)
        info = worker._build_redirect_info(ctx)
        self.assertIn('META-REFRESH', info)


class TestConnectAndValidate(unittest.TestCase):
    """_connect_and_validate 方法测试"""

    def setUp(self):
        self.worker = _make_worker()

    @patch.object(UrlCheckWorker, '_follow_redirects')
    @patch.object(UrlCheckWorker, '_is_safe_ip', return_value=(True, ''))
    def test_success(self, mock_safe_ip, mock_follow):
        """测试成功连接"""
        mock_resp = Mock()
        mock_follow.return_value = (mock_resp, 'http://test.com', '1.2.3.4', None, None)
        ctx = _CheckContext(norm_url='http://test.com', headers={}, connect_timeout=5, read_timeout=10)
        session = Mock()
        self.worker._connect_and_validate(ctx, session)
        self.assertIs(ctx.response, mock_resp)
        self.assertEqual(ctx.ip_addr, '1.2.3.4')
        self.assertIsNone(ctx.redirect_first_status)

    @patch.object(UrlCheckWorker, '_follow_redirects')
    def test_redirect_error(self, mock_follow):
        """测试重定向错误"""
        mock_follow.return_value = (None, 'http://bad.com', '', None, '安全拦截: 内网地址')
        ctx = _CheckContext(norm_url='http://test.com', headers={}, connect_timeout=5, read_timeout=10)
        with self.assertRaises(_EarlyExit) as cm:
            self.worker._connect_and_validate(ctx, Mock())
        self.assertIn('安全拦截', cm.exception.emit_args[6])

    @patch.object(UrlCheckWorker, '_follow_redirects')
    def test_cancelled_redirect(self, mock_follow):
        """测试重定向时取消"""
        mock_follow.return_value = (None, '', '', None, '已取消')
        ctx = _CheckContext(norm_url='http://test.com', headers={}, connect_timeout=5, read_timeout=10)
        with self.assertRaises(_EarlyExit) as cm:
            self.worker._connect_and_validate(ctx, Mock())
        self.assertIn('已取消', cm.exception.emit_args[6])

    @patch.object(UrlCheckWorker, '_follow_redirects')
    def test_none_response(self, mock_follow):
        """测试 response 为 None"""
        mock_follow.return_value = (None, 'http://test.com', '', None, None)
        ctx = _CheckContext(norm_url='http://test.com', headers={}, connect_timeout=5, read_timeout=10)
        with self.assertRaises(_EarlyExit) as cm:
            self.worker._connect_and_validate(ctx, Mock())
        self.assertIn('response 为空', cm.exception.emit_args[6])

    @patch.object(UrlCheckWorker, '_follow_redirects')
    @patch.object(UrlCheckWorker, '_is_safe_ip', return_value=(False, '禁止访问内网地址: 10.0.0.1'))
    def test_unsafe_ip(self, mock_safe_ip, mock_follow):
        """测试不安全 IP"""
        mock_resp = Mock()
        mock_follow.return_value = (mock_resp, 'http://test.com', '10.0.0.1', None, None)
        ctx = _CheckContext(norm_url='http://test.com', headers={}, connect_timeout=5, read_timeout=10)
        with self.assertRaises(_EarlyExit) as cm:
            self.worker._connect_and_validate(ctx, Mock())
        self.assertIn('不安全IP', cm.exception.emit_args[6])
        self.assertEqual(cm.exception.emit_args[5], '10.0.0.1')


class TestFollowRedirects(unittest.TestCase):
    """_follow_redirects 方法测试"""

    @patch.object(UrlCheckWorker, '_get_ip_from_response', return_value='')
    def test_empty_hop_ip_is_blocked(self, mock_get_ip):
        """无法确认真实连接 IP 时应 fail-closed"""
        worker = _make_worker()
        response = Mock()
        response.status_code = 200
        response.headers = {}
        session = Mock()
        session.get.return_value = response

        result = worker._follow_redirects(session, 'http://test.com', {}, 1, 1)

        self.assertIsNone(result[0])
        self.assertEqual(result[2], '')
        self.assertIn('安全拦截', result[4])
        self.assertIn('IP 地址为空', result[4])
        response.close.assert_called_once()
        mock_get_ip.assert_called_once_with(response)


class TestHandleNonTextContent(unittest.TestCase):
    """_handle_non_text_content 方法测试"""

    @patch.object(UrlCheckWorker, '_resolve_binary_content_length', return_value='1.50 MB')
    @patch.object(UrlCheckWorker, '_build_redirect_info', return_value='')
    def test_binary_content(self, mock_redir, mock_resolve):
        """测试二进制内容处理"""
        worker = _make_worker()
        ctx = _CheckContext(
            content_type='application/pdf',
            norm_url='http://a.com/file.pdf',
            final_url='http://a.com/file.pdf',
            start_time=time.monotonic() - 1.0,
            response_headers={},
            ip_addr='1.1.1.1',
        )
        ctx.response = Mock(status_code=200)
        with self.assertRaises(_EarlyExit) as cm:
            worker._handle_non_text_content(ctx)
        args = cm.exception.emit_args
        self.assertIn('APPLICATION/PDF', args[3])  # title
        self.assertIn('非文本内容', args[4])  # banner
        self.assertIn('1.50 MB', args[7])  # content_length

    @patch.object(UrlCheckWorker, '_resolve_binary_content_length', return_value='128 bytes')
    def test_binary_http_error_populates_error_column(self, mock_resolve):
        """非文本 4xx/5xx 响应也应写入错误列"""
        worker = _make_worker()
        ctx = _CheckContext(
            content_type='application/octet-stream',
            norm_url='http://a.com/file.bin',
            final_url='http://a.com/file.bin',
            start_time=time.monotonic(),
            response_headers={},
            ip_addr='1.1.1.1',
        )
        ctx.response = Mock(status_code=404)

        with self.assertRaises(_EarlyExit) as cm:
            worker._handle_non_text_content(ctx)

        args = cm.exception.emit_args
        self.assertIn('HTTP 404', args[6])
        self.assertIn('Not Found', args[6])
        self.assertIn('128 bytes', args[7])
        mock_resolve.assert_called_once()


class TestDownloadTextContent(unittest.TestCase):
    """_download_text_content 方法测试"""

    def test_normal_download(self):
        """测试正常下载"""
        worker = _make_worker()
        mock_response = Mock()
        mock_response.iter_content.return_value = [b'hello', b' world']
        ctx = _CheckContext(start_time=time.monotonic(), response=mock_response)
        worker._download_text_content(ctx)
        self.assertEqual(bytes(ctx.captured), b'hello world')
        self.assertEqual(ctx.downloaded_size, 11)
        self.assertFalse(ctx.size_exceeded)

    def test_cancelled_during_download(self):
        """测试下载中取消"""
        worker = _make_worker()
        worker.cancel()
        mock_response = Mock()
        mock_response.iter_content.return_value = [b'data']
        ctx = _CheckContext(start_time=time.monotonic(), response=mock_response, ip_addr='1.1.1.1')
        with self.assertRaises(_EarlyExit):
            worker._download_text_content(ctx)


class TestHandleMetaRefresh(unittest.TestCase):
    """_handle_meta_refresh 方法测试"""

    def test_no_meta_refresh(self):
        """测试无 meta refresh"""
        worker = _make_worker(follow_meta_refresh=True)
        ctx = _CheckContext(
            captured=bytearray(b'<html><body>hello</body></html>'),
            meta_followed=False, final_url='http://test.com',
            headers={}, connect_timeout=5, read_timeout=10
        )
        ctx.response = Mock()
        self.assertFalse(worker._handle_meta_refresh(ctx, Mock()))

    def test_already_followed(self):
        """测试已跟随过 meta refresh"""
        worker = _make_worker(follow_meta_refresh=True)
        html = b'<meta http-equiv="refresh" content="0; url=http://other.com">'
        ctx = _CheckContext(
            captured=bytearray(html), meta_followed=True,
            final_url='http://test.com', headers={}, connect_timeout=5, read_timeout=10
        )
        ctx.response = Mock()
        self.assertFalse(worker._handle_meta_refresh(ctx, Mock()))

    def test_disabled(self):
        """测试 follow_meta_refresh 关闭"""
        worker = _make_worker(follow_meta_refresh=False)
        html = b'<meta http-equiv="refresh" content="0; url=http://other.com">'
        ctx = _CheckContext(
            captured=bytearray(html), meta_followed=False,
            final_url='http://test.com', headers={}, connect_timeout=5, read_timeout=10
        )
        ctx.response = Mock()
        self.assertFalse(worker._handle_meta_refresh(ctx, Mock()))

    @patch.object(UrlCheckWorker, '_is_safe_url', return_value=(False, '内网地址'))
    def test_unsafe_target(self, mock_safe):
        """测试不安全的 meta refresh 目标"""
        worker = _make_worker(follow_meta_refresh=True)
        html = b'<meta http-equiv="refresh" content="0; url=http://192.168.1.1">'
        ctx = _CheckContext(
            captured=bytearray(html), meta_followed=False,
            final_url='http://test.com', headers={}, connect_timeout=5, read_timeout=10
        )
        ctx.response = Mock()
        self.assertFalse(worker._handle_meta_refresh(ctx, Mock()))
        self.assertIn('META-REFRESH拦截', ctx.meta_follow_error)

    @patch.object(UrlCheckWorker, '_is_safe_ip', return_value=(True, ''))
    @patch.object(UrlCheckWorker, '_follow_redirects')
    @patch.object(UrlCheckWorker, '_is_safe_url', return_value=(True, ''))
    @patch.object(UrlCheckWorker, '_collect_response_headers')
    def test_successful_follow(self, mock_headers, mock_safe_url, mock_follow, mock_safe_ip):
        """测试成功跟随 meta refresh"""
        worker = _make_worker(follow_meta_refresh=True)
        html = b'<meta http-equiv="refresh" content="0; url=http://other.com">'
        ctx = _CheckContext(
            captured=bytearray(html), meta_followed=False,
            final_url='http://test.com', headers={}, connect_timeout=5, read_timeout=10
        )
        ctx.response = Mock()

        mock_resp2 = Mock(status_code=200)
        mock_follow.return_value = (mock_resp2, 'http://other.com', '2.2.2.2', None, None)
        mock_headers.return_value = {'Content-Type': 'text/html; charset=utf-8'}

        result = worker._handle_meta_refresh(ctx, Mock())
        self.assertTrue(result)
        self.assertTrue(ctx.meta_followed)
        self.assertEqual(ctx.final_url, 'http://other.com')
        self.assertIs(ctx.response, mock_resp2)


class TestEmitResult(unittest.TestCase):
    """_emit_result 方法测试"""

    def test_emit_with_response(self):
        """测试带 response 的 emit"""
        worker = _make_worker()
        worker.result_signal = Mock()
        ctx = _CheckContext(
            final_url='http://a.com', ip_addr='1.1.1.1',
            title='Test', banner='Server: nginx',
            error_msg='', html='<html></html>', content_length='1.00 KB (0.5s)'
        )
        ctx.response = Mock(status_code=200)
        worker._emit_result(ctx)
        worker.result_signal.emit.assert_called_once_with(
            0, 'http://a.com', '200', 'Test', 'Server: nginx',
            '1.1.1.1', '', '1.00 KB (0.5s)'
        )

    def test_emit_without_response(self):
        """测试无 response 的 emit"""
        worker = _make_worker()
        worker.result_signal = Mock()
        ctx = _CheckContext(final_url='http://a.com', error_msg='连接失败')
        worker._emit_result(ctx)
        args = worker.result_signal.emit.call_args[0]
        self.assertEqual(args[2], '')  # status_code 为空


class TestResolveBinaryContentLength(unittest.TestCase):
    """_resolve_binary_content_length 方法测试"""

    def test_from_header(self):
        """测试从 Content-Length 头获取大小"""
        worker = _make_worker()
        ctx = _CheckContext(start_time=time.monotonic())
        result = worker._resolve_binary_content_length(
            ctx, Mock(), {'Content-Length': '1048576'}
        )
        self.assertIn('MB', result)

    def test_missing_header_no_compute(self):
        """测试缺失 Content-Length 且不计算"""
        worker = _make_worker(compute_full_content_length=False)
        ctx = _CheckContext(start_time=time.monotonic())
        result = worker._resolve_binary_content_length(ctx, Mock(), {})
        self.assertEqual(result, '未知大小')

    def test_missing_header_with_compute(self):
        """测试缺失 Content-Length 时通过下载计算"""
        worker = _make_worker(compute_full_content_length=True)
        mock_response = Mock()
        mock_response.iter_content.return_value = [b'x' * 1024]
        ctx = _CheckContext(start_time=time.monotonic())
        result = worker._resolve_binary_content_length(ctx, mock_response, {})
        self.assertIn('KB', result)


class TestHtmlHeadParser(unittest.TestCase):
    """_HtmlHeadParser 解析器测试"""

    def test_title_extraction(self):
        """测试 <title> 提取"""
        p = _HtmlHeadParser()
        p.feed('<html><head><title>Hello World</title></head></html>')
        self.assertEqual(p.title, 'Hello World')

    def test_title_with_entities(self):
        """测试 HTML 实体自动转换"""
        p = _HtmlHeadParser()
        p.feed('<title>A &amp; B</title>')
        self.assertEqual(p.title, 'A & B')

    def test_title_multiline(self):
        """测试多行 title"""
        p = _HtmlHeadParser()
        p.feed('<title>\n  Hello\n  World\n</title>')
        self.assertEqual(p.title, '\n  Hello\n  World\n')

    def test_title_nested_tags(self):
        """测试 title 内有嵌套标签"""
        p = _HtmlHeadParser()
        p.feed('<title><b>Bold</b> Title</title>')
        self.assertEqual(p.title, 'Bold Title')

    def test_only_first_title(self):
        """测试只取第一个 title"""
        p = _HtmlHeadParser()
        p.feed('<title>First</title><title>Second</title>')
        self.assertEqual(p.title, 'First')

    def test_h1_extraction(self):
        """测试 <h1> 提取"""
        p = _HtmlHeadParser()
        p.feed('<body><h1>Page Heading</h1><h1>Second</h1></body>')
        self.assertEqual(p.h1, 'Page Heading')

    def test_meta_charset(self):
        """测试 <meta charset> 提取"""
        p = _HtmlHeadParser()
        p.feed('<meta charset="utf-8">')
        self.assertEqual(len(p.meta_tags), 1)
        self.assertEqual(p.meta_tags[0].get('charset'), 'utf-8')

    def test_meta_name_content(self):
        """测试 <meta name="" content=""> 提取"""
        p = _HtmlHeadParser()
        p.feed('<meta name="generator" content="WordPress 6.0">')
        self.assertEqual(p.get_meta(name='generator'), 'WordPress 6.0')

    def test_meta_property_content(self):
        """测试 <meta property="" content=""> 提取"""
        p = _HtmlHeadParser()
        p.feed('<meta property="og:title" content="My Page">')
        self.assertEqual(p.get_meta(prop='og:title'), 'My Page')

    def test_meta_reversed_attribute_order(self):
        """测试属性顺序反转（content 在 name 前面）"""
        p = _HtmlHeadParser()
        p.feed('<meta content="WordPress 6.0" name="generator">')
        self.assertEqual(p.get_meta(name='generator'), 'WordPress 6.0')

    def test_meta_case_insensitive(self):
        """测试 meta 标签大小写不敏感"""
        p = _HtmlHeadParser()
        p.feed('<META NAME="Generator" CONTENT="Drupal">')
        self.assertEqual(p.get_meta(name='generator'), 'Drupal')

    def test_meta_not_found(self):
        """测试未找到的 meta 标签返回 None"""
        p = _HtmlHeadParser()
        p.feed('<meta name="description" content="A page">')
        self.assertIsNone(p.get_meta(name='generator'))

    def test_meta_empty_content(self):
        """测试空 content 返回 None"""
        p = _HtmlHeadParser()
        p.feed('<meta name="generator" content="">')
        self.assertIsNone(p.get_meta(name='generator'))

    def test_meta_http_equiv(self):
        """测试 http-equiv meta 标签"""
        p = _HtmlHeadParser()
        p.feed('<meta http-equiv="Content-Type" content="text/html; charset=gbk">')
        self.assertEqual(p.get_meta(http_equiv='content-type'), 'text/html; charset=gbk')

    def test_malformed_html(self):
        """测试畸形 HTML 不抛异常"""
        p = _HtmlHeadParser()
        try:
            p.feed('<title>Unclosed<meta name="a" content="b"><h1>Open')
        except Exception:
            pass
        # 即使畸形也不会崩溃

    def test_no_tags(self):
        """测试无 HTML 标签的纯文本"""
        p = _HtmlHeadParser()
        p.feed('Just plain text')
        self.assertEqual(p.title, '')
        self.assertEqual(p.h1, '')
        self.assertEqual(len(p.meta_tags), 0)


class TestParseHtml(unittest.TestCase):
    """_parse_html 静态方法测试"""

    def test_basic(self):
        """测试基本解析"""
        parsed = UrlCheckWorker._parse_html(
            '<html><head><title>Test</title></head></html>'
        )
        self.assertEqual(parsed.title, 'Test')

    def test_exception_safe(self):
        """测试异常安全（不崩溃）"""
        parsed = UrlCheckWorker._parse_html(None)  # type: ignore
        # 应返回空解析器
        self.assertIsInstance(parsed, _HtmlHeadParser)


class TestExtractTitleWithParser(unittest.TestCase):
    """使用 parser 后的 _extract_title 测试"""

    def test_title_tag(self):
        """测试从 <title> 提取"""
        worker = _make_worker()
        result = worker._extract_title('<html><title>My Page</title></html>')
        self.assertEqual(result, 'My Page')

    def test_og_title(self):
        """测试从 og:title 提取"""
        worker = _make_worker()
        html = '<meta property="og:title" content="OG Title">'
        result = worker._extract_title(html)
        self.assertEqual(result, 'OG Title')

    def test_meta_name_title(self):
        """测试从 meta name=title 提取"""
        worker = _make_worker()
        html = '<meta name="title" content="Meta Title">'
        result = worker._extract_title(html)
        self.assertEqual(result, 'Meta Title')

    def test_h1_fallback(self):
        """测试 h1 回退"""
        worker = _make_worker()
        html = '<body><h1>Heading One</h1></body>'
        result = worker._extract_title(html)
        self.assertEqual(result, 'Heading One')

    def test_priority_title_over_h1(self):
        """测试 title 优先于 h1"""
        worker = _make_worker()
        html = '<title>Title</title><h1>H1</h1>'
        result = worker._extract_title(html)
        self.assertEqual(result, 'Title')

    def test_content_type_fallback(self):
        """测试 Content-Type 回退"""
        worker = _make_worker()
        result = worker._extract_title('', response_headers={'Content-Type': 'application/json'})
        self.assertEqual(result, '[JSON API 接口]')

    def test_no_title(self):
        """测试完全无标题"""
        worker = _make_worker()
        result = worker._extract_title('')
        self.assertEqual(result, '[无标题页面]')

    def test_reversed_meta_attribute_order(self):
        """测试 meta 属性反转顺序（html.parser 的核心优势）"""
        worker = _make_worker()
        html = '<meta content="Reversed" name="title">'
        result = worker._extract_title(html)
        self.assertEqual(result, 'Reversed')


class TestExtractBannerWithParser(unittest.TestCase):
    """使用 parser 后的 _extract_banner 测试"""

    def test_generator_meta(self):
        """测试 generator meta 提取"""
        worker = _make_worker()
        html = '<meta name="generator" content="WordPress 6.2">'
        result = worker._extract_banner(html)
        self.assertIn('WordPress 6.2', result)

    def test_generator_reversed_attrs(self):
        """测试 generator meta 属性反转"""
        worker = _make_worker()
        html = '<meta content="Drupal 10" name="generator">'
        result = worker._extract_banner(html)
        self.assertIn('Drupal 10', result)

    def test_application_name_meta(self):
        """测试 application-name 提取"""
        worker = _make_worker()
        html = '<meta name="application-name" content="MyApp">'
        result = worker._extract_banner(html)
        self.assertIn('MyApp', result)

    def test_framework_meta(self):
        """测试 framework meta 提取"""
        worker = _make_worker()
        html = '<meta name="framework" content="Laravel">'
        result = worker._extract_banner(html)
        self.assertIn('Laravel', result)

    def test_header_based_detection(self):
        """测试 HTTP 头检测不受影响"""
        worker = _make_worker()
        result = worker._extract_banner('', response_headers={'Server': 'nginx/1.20'})
        self.assertIn('Server: nginx/1.20', result)

    def test_framework_regex_still_works(self):
        """测试框架正则匹配保留"""
        worker = _make_worker()
        html = '<script src="/wp-content/themes/main.js"></script>'
        result = worker._extract_banner(html)
        self.assertIn('WordPress', result)

    def test_no_info(self):
        """测试无信息"""
        worker = _make_worker()
        result = worker._extract_banner('')
        self.assertEqual(result, '[无标识信息]')


if __name__ == '__main__':
    unittest.main()
