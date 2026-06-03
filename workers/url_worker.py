# URL检查和页面信息提取模块
# 实现异步URL访问、内容提取、安全防护功能

import time
import socket
import threading
import ipaddress
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse, urljoin
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget
import requests
import urllib3
from requests.exceptions import Timeout

from utils import RegexCache, normalize_url, validate_cookie, DANGEROUS_PORTS
from utils.logger import get_logger
from utils.page_info_extractor import (
    DEFAULT_FRAMEWORK_PATTERNS,
    HtmlHeadParser,
    decode_html_intelligently as decode_html_content,
    extract_banner as extract_banner_info,
    extract_first_visible_text as extract_visible_text,
    extract_page_info as extract_html_page_info,
    extract_title as extract_html_title,
    parse_html as parse_html_head,
)
from utils.url_safety import (
    is_safe_ip as check_safe_ip,
    is_safe_url as check_safe_url,
    validate_ip_object as validate_safe_ip_object,
)

# 模块级日志记录器
logger = get_logger('url_worker')

# 在模块级别禁用 SSL 警告，避免 Nuitka 编译后的 warnings 模块问题
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def sanitize_url_for_export(url: str) -> str:
    # 全局函数：供外部调用的URL脱敏方法
    # 用于导出CSV或日志时脱敏敏感参数
    try:
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

        parsed = urlparse(url)

        # 解析 query / fragment（OAuth 隐式回调常把 token 放在 #fragment）
        params = parse_qs(parsed.query, keep_blank_values=True) if parsed.query else {}
        frag_params = None
        if parsed.fragment and ("=" in parsed.fragment or "&" in parsed.fragment):
            frag_params = parse_qs(parsed.fragment, keep_blank_values=True)

        # 需要脱敏的参数名（不区分大小写）
        sensitive_keys = [
            'token', 'access_token', 'refresh_token', 'auth_token', 'bearer_token',
            'api_key', 'apikey', 'key', 'app_key', 'application_key',
            'secret', 'app_secret', 'client_secret', 'consumer_secret',
            'password', 'passwd', 'pwd', 'pass',
            'session', 'session_id', 'sessionid', 'sessid',
            'auth', 'authorization', 'credentials',
            'private_key', 'privatekey', 'priv_key',
            'signature', 'sign', 'sig',
            'jwt', 'id_token',
        ]

        def should_redact_key(key_name: str) -> bool:
            k = key_name.lower()
            if k in sensitive_keys:
                return True
            return any(s in k for s in ('token', 'secret', 'key', 'password', 'auth'))

        def redact_params(d: dict) -> bool:
            changed = False
            for key in list(d.keys()):
                if should_redact_key(key):
                    d[key] = ['***REDACTED***']
                    changed = True
            return changed

        # 脱敏处理
        sanitized = False
        sanitized = redact_params(params) or sanitized
        if frag_params is not None:
            sanitized = redact_params(frag_params) or sanitized

        fragment = parsed.fragment
        if frag_params is None and fragment:
            # 非参数形式的 fragment（如 #/route），仅在疑似敏感时整体遮蔽
            frag_lower = fragment.lower()
            if any(s in frag_lower for s in ('token', 'access_token', 'refresh_token', 'jwt', 'secret', 'apikey', 'api_key')):
                fragment = '***REDACTED***'
                sanitized = True

        # 如果进行了脱敏，重新构建URL
        if sanitized:
            new_query = urlencode(params, doseq=True) if params else ''
            new_fragment = urlencode(frag_params, doseq=True) if frag_params is not None else fragment
            sanitized_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                new_fragment
            ))
            return sanitized_url

        return url

    except Exception:
        # 如果脱敏失败，返回原URL（至少不会中断功能）
        return url


# 在错误/日志字符串中查找 URL 并整体替换为脱敏后的版本
_URL_IN_TEXT_RE = re.compile(r'https?://[^\s\'"\)<>]+', re.IGNORECASE)


def _sanitize_error(text: str) -> str:
    # 把错误字符串里嵌入的 URL 做脱敏替换，避免 token/key 泄漏到 UI/CSV
    if not text:
        return text
    try:
        return _URL_IN_TEXT_RE.sub(lambda m: sanitize_url_for_export(m.group(0)), text)
    except Exception:
        return text


class _EarlyExit(BaseException):
    # run() 内部提前退出，携带需要 emit 的 8 元组参数
    # 继承 BaseException 避免被 except Exception 捕获
    def __init__(self, *emit_args):
        self.emit_args = emit_args


@dataclass
class _CheckContext:
    # run() 方法各阶段共享的可变状态
    norm_url: str = ''
    headers: dict = field(default_factory=dict)
    start_time: float = 0.0
    connect_timeout: float = 0.0
    read_timeout: float = 0.0
    response: Optional['requests.Response'] = None
    final_url: str = ''
    ip_addr: str = ''
    redirect_first_status: Optional[int] = None
    response_headers: dict = field(default_factory=dict)
    content_type: str = ''
    is_text_content: bool = False
    captured: bytearray = field(default_factory=bytearray)
    downloaded_size: int = 0
    size_exceeded: bool = False
    capture_exceeded: bool = False
    content_length: str = '0 bytes'
    response_time: float = 0.0
    html: str = ''
    title: str = ''
    banner: str = ''
    redirect_info: str = ''
    meta_note: str = ''
    meta_follow_error: str = ''
    meta_followed: bool = False
    error_msg: str = ''


_HtmlHeadParser = HtmlHeadParser  # _parse_html 的返回类型注解使用


class UrlCheckWorker(QThread):
    # URL异步检查工作线程，支持SSL验证、大小限制、Cookie验证

    # 安全限制（防止内存耗尽、重定向循环等攻击）
    MAX_CONTENT_SIZE = 10 * 1024 * 1024  # 10MB上限
    CHUNK_SIZE = 8192                     # 8KB分块
    MAX_REDIRECTS = 10                    # 10次重定向
    CONNECT_TIMEOUT = 5                   # 连接超时（秒）
    READ_TIMEOUT = 10                     # 读取超时（秒）
    MAX_TOTAL_TIME = 15                   # 单个URL最大总耗时（秒，防止慢速/卡死连接）
    # 对于“无 scheme 的 URL”，先尝试 https 但要更快失败，避免每个 http-only 目标都卡 5 秒
    CONNECT_TIMEOUT_SCHEMELESS_HTTPS = 2  # 仅用于 https://{host} 这类自动补全的首次尝试
    READ_TIMEOUT_SCHEMELESS_HTTPS = 6
    ENCODING_DETECT_SIZE = 1024           # 编码检测样本大小
    FRAMEWORK_SEARCH_SIZE = 50000         # 框架识别搜索范围（前50KB）
    # 页面内容只保留前 N 字节用于标题/指纹/内容预览，避免大页面拖慢整体批量扫描
    MAX_BODY_CAPTURE_SIZE = 512 * 1024    # 512KB

    # HTTP状态码字典（类变量，避免重复创建）
    STATUS_DESCRIPTIONS = {
        100: 'Continue (继续)', 101: 'Switching Protocols (切换协议)',
        200: 'OK (请求成功)', 201: 'Created (已创建)', 202: 'Accepted (已接受)',
        203: 'Non-Authoritative Information (非授权信息)', 204: 'No Content (无内容)',
        205: 'Reset Content (重置内容)', 206: 'Partial Content (部分内容)',
        300: 'Multiple Choices (多种选择)', 301: 'Moved Permanently (永久移动)',
        302: 'Found (临时移动)', 303: 'See Other (查看其他位置)',
        304: 'Not Modified (未修改)', 305: 'Use Proxy (使用代理)',
        307: 'Temporary Redirect (临时重定向)', 308: 'Permanent Redirect (永久重定向)',
        400: 'Bad Request (错误请求)', 401: 'Unauthorized (未授权)',
        402: 'Payment Required (需要支付)', 403: 'Forbidden (禁止访问)',
        404: 'Not Found (未找到)', 405: 'Method Not Allowed (方法不允许)',
        406: 'Not Acceptable (不可接受)', 407: 'Proxy Authentication Required (代理认证要求)',
        408: 'Request Timeout (请求超时)', 409: 'Conflict (冲突)',
        410: 'Gone (已删除)', 411: 'Length Required (需要长度)',
        412: 'Precondition Failed (先决条件失败)', 413: 'Payload Too Large (请求实体过大)',
        414: 'URI Too Long (请求的URI过长)', 415: 'Unsupported Media Type (不支持的媒体类型)',
        416: 'Range Not Satisfiable (请求范围不满足)', 417: 'Expectation Failed (期望失败)',
        418: 'I\'m a teapot (我是一个茶壶)', 421: 'Misdirected Request (错误的请求)',
        422: 'Unprocessable Entity (无法处理的实体)', 423: 'Locked (已锁定)',
        424: 'Failed Dependency (依赖失败)', 425: 'Too Early (过早的请求)',
        426: 'Upgrade Required (需要升级)', 428: 'Precondition Required (需要先决条件)',
        429: 'Too Many Requests (请求过多)', 431: 'Request Header Fields Too Large (请求头字段过大)',
        451: 'Unavailable For Legal Reasons (因法律原因不可用)',
        500: 'Internal Server Error (服务器内部错误)', 501: 'Not Implemented (未实现)',
        502: 'Bad Gateway (网关错误)', 503: 'Service Unavailable (服务不可用)',
        504: 'Gateway Timeout (网关超时)', 521: 'Web Server Is Down (Web服务器已关闭)',
        522: 'Connection Timed Out (连接超时)', 523: 'Origin Is Unreachable (源站不可达)',
        524: 'A Timeout Occurred (发生超时)'
    }

    # 框架/中间件识别模式（预编译，避免每次调用 _extract_banner 重建）
    _FRAMEWORK_PATTERNS = DEFAULT_FRAMEWORK_PATTERNS

    # 信号：(行号, URL, 状态码, 标题, Banner, IP, 错误信息, 大小)
    result_signal = pyqtSignal(int, str, str, str, str, str, str, str)

    def __init__(
        self,
        row: int,
        url: str,
        parent: Optional[QWidget] = None,
        verify_ssl: bool = True,
        allow_internal: bool = False,
        downgrade_https: bool = False,
        compute_full_content_length: bool = False,
        follow_meta_refresh: bool = False,
        user_agent: str = 'Mozilla/5.0',
        cookie: str = '',
    ) -> None:
        super().__init__(parent)
        self.row = row
        self.url = url
        self.verify_ssl = verify_ssl
        self.allow_internal = allow_internal
        self.downgrade_https = downgrade_https
        self.compute_full_content_length = bool(compute_full_content_length)
        self.follow_meta_refresh = bool(follow_meta_refresh)
        stripped_ua = user_agent.strip() if user_agent else ''
        self.user_agent = stripped_ua or 'Mozilla/5.0'
        self.cookie = cookie.strip() if cookie else ''
        self._cancel_event = threading.Event()

    def cancel(self):
        # 取消当前URL检查任务
        self._cancel_event.set()

    @property
    def _is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def _check_cancelled(self, ctx: '_CheckContext' = None) -> None:
        # 如果已取消，抛出 _EarlyExit
        if self._is_cancelled:
            ip = ctx.ip_addr if ctx else ''
            raise _EarlyExit(self.row, self.url, '', '', '', ip, '已取消', '')

    def _emit_result(self, ctx: '_CheckContext') -> None:
        # 从 context 发射完整结果信号
        status_code = str(ctx.response.status_code) if ctx.response else ''
        self.result_signal.emit(
            self.row, ctx.final_url, status_code,
            ctx.title, ctx.banner, ctx.ip_addr, _sanitize_error(ctx.error_msg), ctx.content_length
        )

    def _compute_timeouts(self, urls_to_try: list, original_has_scheme: bool, norm_url: str) -> Tuple[float, float]:
        # 根据是否为自动补全的 https 首次尝试，计算超时
        connect_timeout = self.CONNECT_TIMEOUT
        read_timeout = self.READ_TIMEOUT
        if (not original_has_scheme and norm_url.startswith('https://')
                and len(urls_to_try) > 1 and urls_to_try[1].startswith('http://')):
            connect_timeout = min(connect_timeout, self.CONNECT_TIMEOUT_SCHEMELESS_HTTPS)
            read_timeout = min(read_timeout, self.READ_TIMEOUT_SCHEMELESS_HTTPS)
        return connect_timeout, read_timeout

    @staticmethod
    def _parse_content_length_header(response_headers: dict) -> Optional[int]:
        # 从 Content-Length 头解析字节数
        content_len = str(response_headers.get('Content-Length', '') or '').strip()
        if not content_len:
            return None
        try:
            return int(content_len)
        except (ValueError, TypeError):
            return None

    def _build_redirect_info(self, ctx: '_CheckContext') -> str:
        # 构建重定向描述字符串
        redirect_info = ''
        if ctx.redirect_first_status is not None:
            redirect_info = f"[重定向: {ctx.redirect_first_status} → {ctx.response.status_code}]"
            if ctx.final_url != ctx.norm_url:
                redirect_info += f" → {ctx.final_url}"
        if ctx.meta_note:
            redirect_info = (redirect_info + ' ' if redirect_info else '') + ctx.meta_note
        return redirect_info

    def _build_http_error(self, status_code: int) -> str:
        # 统一构建 HTTP 4xx/5xx 错误描述，文本和非文本响应共用。
        if status_code >= 400:
            return (
                f"HTTP {status_code} - "
                f"{self.STATUS_DESCRIPTIONS.get(status_code, '客户端或服务器错误')}"
            )
        return ''

    def _format_size(self, size_bytes: int, exceeded: bool = False) -> str:
        # 格式化文件大小为人类可读格式
        if exceeded:
            return f'{size_bytes / (1024*1024):.2f} MB (超限截断)'
        if size_bytes >= 1024 * 1024:
            return f'{size_bytes / (1024*1024):.2f} MB'
        elif size_bytes >= 1024:
            return f'{size_bytes / 1024:.2f} KB'
        else:
            return f'{size_bytes} bytes'

    def _get_ip_from_response(self, response: requests.Response) -> str:
        # 从响应对象中提取服务器IP地址
        try:
            conn = getattr(response.raw, '_connection', None)
            sock = getattr(conn, 'sock', None) if conn else None
            if sock:
                peer = sock.getpeername()
                return peer[0] if isinstance(peer, tuple) else str(peer)
            elif hasattr(response.raw, '_fp') and hasattr(response.raw._fp, 'fp'):
                raw_sock = getattr(response.raw._fp.fp, 'raw', None)
                if raw_sock and hasattr(raw_sock, 'sock'):
                    peer = raw_sock.sock.getpeername()
                    return peer[0] if isinstance(peer, tuple) else str(peer)
        except Exception as e:
            logger.debug(f"IP提取失败: {type(e).__name__}: {e}")

        # Fallback: socket 已关闭（如 Connection: close），通过 DNS 解析获取 IP。
        # 注意：此处 DNS 解析与实际连接时 urllib3 内部解析、与 is_safe_url 的预解析
        # 是三次独立解析，理论上可能不一致（DNS rebinding 时间窗）。但放弃 fallback
        # 会让所有 Connection: close 连接都因取不到 peer IP 而被 _is_safe_ip('')
        # 拒绝（破坏功能）。当前 fallback 仍由调用方做 _is_safe_ip 二次校验，
        # DNS rebinding 是低概率理论攻击，暂保留。
        try:
            hostname = urlparse(response.url).hostname
            if hostname:
                ip = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)[0][4][0]
                return ip
        except Exception as e:
            logger.debug(f"DNS fallback 失败: {type(e).__name__}: {e}")

        logger.debug(f"无法提取IP地址: {response.url}")
        return ''

    def _build_headers(self) -> dict:
        # 构建HTTP请求头
        headers = {
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        if self.cookie:
            headers['Cookie'] = self.cookie
        return headers

    def _prepare_urls(self) -> Tuple[list, bool, Optional[str]]:
        # 准备URL列表并进行验证
        # 返回: (urls_to_try, original_has_scheme, error_msg)
        urls_to_try = normalize_url(self.url)
        original_has_scheme = self.url.strip().startswith(('http://', 'https://'))

        # 可选：当用户显式输入 https:// 时，允许在失败时额外尝试 http://
        if self.downgrade_https and self.url.strip().lower().startswith('https://') and len(urls_to_try) == 1:
            urls_to_try.append('http://' + self.url.strip()[len('https://'):])

        # Cookie 验证
        if self.cookie:
            is_valid, cleaned_cookie, error_msg = validate_cookie(self.cookie)
            if not is_valid:
                return [], original_has_scheme, f'Cookie错误: {error_msg}'
            self.cookie = cleaned_cookie

        if not urls_to_try:
            return [], original_has_scheme, '无效的URL'

        return urls_to_try, original_has_scheme, None

    def _follow_redirects(
        self,
        session: requests.Session,
        start_url: str,
        headers: dict,
        connect_timeout: float,
        read_timeout: float
    ) -> Tuple[Optional[requests.Response], str, str, Optional[int], Optional[str]]:
        # 手动处理重定向，对每一次 Location 做 URL 级 SSRF 校验，并对每次连接
        # 拿到的真实 socket IP 做 IP 级校验（防御 DNS rebinding / 公网域名指向内网）。
        # 返回: (response, final_url, ip_addr, redirect_first_status, error_msg)
        redirect_first_status: Optional[int] = None
        final_url = start_url
        response: Optional[requests.Response] = None
        ip_addr = ''
        # 用 (scheme, netloc, path) 作为循环键，避免用 query/fragment 变化绕过
        visited_keys: set = set()

        def _canonical_key(u: str) -> tuple:
            try:
                p = urlparse(u)
                return (p.scheme.lower(), (p.netloc or '').lower(), p.path or '/')
            except Exception:
                return ('', u, '')

        visited_keys.add(_canonical_key(final_url))

        for _ in range(self.MAX_REDIRECTS + 1):
            if self._is_cancelled:
                return None, final_url, '', None, '已取消'

            response = session.get(
                final_url,
                timeout=(connect_timeout, read_timeout),
                verify=self.verify_ssl,
                allow_redirects=False,
                headers=headers,
                stream=True,
            )

            # 每跳都要拿 IP 做 SSRF 二次校验。无法确认真实连接 IP 时 fail-closed。
            hop_ip = self._get_ip_from_response(response)
            ip_safe, ip_err = self._is_safe_ip(hop_ip)
            if not ip_safe:
                try:
                    response.close()
                except Exception:
                    pass
                return None, final_url, hop_ip, redirect_first_status, f'安全拦截: 解析到不安全IP: {ip_err}'

            if response.status_code in (301, 302, 303, 307, 308) and response.headers.get('Location'):
                if redirect_first_status is None:
                    redirect_first_status = response.status_code

                location = response.headers.get('Location', '').strip()
                response.close()
                response = None

                if not location:
                    break

                next_url = urljoin(final_url, location)

                # 规范键检测循环
                key = _canonical_key(next_url)
                if key in visited_keys:
                    return None, next_url, '', redirect_first_status, '安全拦截: 检测到循环重定向'
                visited_keys.add(key)

                is_safe, safety_error = self._is_safe_url(next_url)
                if not is_safe:
                    return None, next_url, '', redirect_first_status, f'安全拦截: 重定向到不安全地址: {safety_error}'

                final_url = next_url
                continue

            # 非重定向：用这一跳的 IP 作为最终 IP
            ip_addr = hop_ip
            break
        else:
            if response is not None:
                response.close()
            raise requests.exceptions.TooManyRedirects

        return response, final_url, ip_addr, redirect_first_status, None

    def _validate_ip_object(self, ip: 'ipaddress.IPv4Address | ipaddress.IPv6Address', label: str) -> Tuple[bool, str]:
        return validate_safe_ip_object(ip, label, allow_internal=self.allow_internal)

    def _is_safe_ip(self, ip_str: str) -> Tuple[bool, str]:
        return check_safe_ip(ip_str, allow_internal=self.allow_internal, logger=logger)

    def _is_safe_url(self, url: str) -> Tuple[bool, str]:
        return check_safe_url(url, allow_internal=self.allow_internal, dangerous_ports=DANGEROUS_PORTS)

    def _connect_and_validate(self, ctx: '_CheckContext', session: 'requests.Session') -> None:
        # 调用 _follow_redirects，处理重定向错误，做 SSRF IP 校验
        # 成功时填充 ctx，失败时 raise _EarlyExit
        response, final_url, ip_addr, redirect_first_status, redirect_error = self._follow_redirects(
            session, ctx.norm_url, ctx.headers, ctx.connect_timeout, ctx.read_timeout
        )
        if redirect_error:
            url = self.url if redirect_error == '已取消' else final_url
            raise _EarlyExit(self.row, url, '', '', '', '', redirect_error, '')

        if response is None:
            raise _EarlyExit(self.row, ctx.norm_url, '', '', '', '', '内部错误: response 为空', '')

        ip_safe, ip_err = self._is_safe_ip(ip_addr)
        if not ip_safe:
            try:
                response.close()
            except Exception:
                pass
            raise _EarlyExit(self.row, final_url, '', '', '', ip_addr,
                             f'安全拦截: 解析到不安全IP: {ip_err}', '')

        ctx.response = response
        ctx.final_url = final_url
        ctx.ip_addr = ip_addr
        ctx.redirect_first_status = redirect_first_status

    def _resolve_binary_content_length(self, ctx: '_CheckContext', response: 'requests.Response',
                                       response_headers: dict) -> str:
        # 计算非文本内容的 content_length 字符串
        size_bytes = self._parse_content_length_header(response_headers)

        if size_bytes is None and self.compute_full_content_length:
            downloaded: Optional[int] = 0
            exceeded = False
            try:
                for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                    self._check_cancelled(ctx)
                    if time.monotonic() - ctx.start_time > self.MAX_TOTAL_TIME:
                        raise requests.exceptions.Timeout(f'总耗时超过{self.MAX_TOTAL_TIME}秒')
                    if chunk:
                        downloaded += len(chunk)
                        if downloaded > self.MAX_CONTENT_SIZE:
                            exceeded = True
                            break
            except _EarlyExit:
                raise
            except Exception as e:
                logger.debug(f"Content-Length计算失败: {type(e).__name__}: {e}")
                downloaded = None

            if downloaded is None:
                return '未知大小'
            return self._format_size(downloaded, exceeded)
        elif size_bytes is not None:
            return self._format_size(size_bytes)
        else:
            return '未知大小'

    def _handle_non_text_content(self, ctx: '_CheckContext') -> None:
        # 处理非文本内容（二进制文件等），emit 结果后 raise _EarlyExit
        file_type = ctx.content_type.split(';')[0].strip()
        title = f'[{file_type.upper()}]'
        banner = f'非文本内容 ({file_type})'

        content_length = self._resolve_binary_content_length(ctx, ctx.response, ctx.response_headers)
        response_time = time.monotonic() - ctx.start_time
        content_length += f' ({response_time:.2f}s)'

        redirect_info = self._build_http_error(ctx.response.status_code) or self._build_redirect_info(ctx)

        raise _EarlyExit(
            self.row, ctx.final_url, str(ctx.response.status_code),
            title, banner, ctx.ip_addr, redirect_info, content_length
        )

    def _download_text_content(self, ctx: '_CheckContext') -> None:
        # 分块下载文本内容到 ctx.captured
        ctx.captured = bytearray()
        ctx.downloaded_size = 0
        ctx.size_exceeded = False
        ctx.capture_exceeded = False

        for chunk in ctx.response.iter_content(chunk_size=self.CHUNK_SIZE):
            self._check_cancelled(ctx)
            if time.monotonic() - ctx.start_time > self.MAX_TOTAL_TIME:
                raise requests.exceptions.Timeout(f'总耗时超过{self.MAX_TOTAL_TIME}秒')

            if chunk:
                ctx.downloaded_size += len(chunk)

                if ctx.downloaded_size > self.MAX_CONTENT_SIZE:
                    ctx.size_exceeded = True
                    ctx.content_length = f'{ctx.downloaded_size / (1024*1024):.2f} MB (超限截断)'
                    break

                if len(ctx.captured) < self.MAX_BODY_CAPTURE_SIZE:
                    remaining = self.MAX_BODY_CAPTURE_SIZE - len(ctx.captured)
                    ctx.captured.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        ctx.capture_exceeded = True
                        if not self.compute_full_content_length:
                            break
                else:
                    ctx.capture_exceeded = True
                    if not self.compute_full_content_length:
                        break

    def _handle_meta_refresh(self, ctx: '_CheckContext', session: 'requests.Session') -> bool:
        # 尝试跟随 meta refresh，返回 True 表示已切换 response 需要重新下载
        if not self.follow_meta_refresh or ctx.meta_followed:
            return False

        # 扩大扫描窗口到 64KB，应对 <meta> 位于大量注释/CSS 之后的场景
        delay, target = self._parse_meta_refresh(bytes(ctx.captured)[:65536])
        if not target or delay is None or delay > 1:
            return False

        next_url = urljoin(ctx.final_url, target)
        is_safe, safety_error = self._is_safe_url(next_url)
        if not is_safe:
            ctx.meta_follow_error = f"META-REFRESH拦截: {safety_error}"
            return False

        try:
            response2, final_url2, ip_addr2, redirect_first_status2, redirect_error2 = self._follow_redirects(
                session, next_url, ctx.headers, ctx.connect_timeout, ctx.read_timeout
            )
        except requests.exceptions.RequestException as e:
            ctx.meta_follow_error = f"META-REFRESH失败: {self._parse_connection_error(e)}"
            return False

        if redirect_error2:
            if redirect_error2 == '已取消':
                raise _EarlyExit(self.row, self.url, '', '', '', '', '已取消', '')
            ctx.meta_follow_error = f"META-REFRESH拦截: {redirect_error2}"
            return False

        if response2 is None:
            ctx.meta_follow_error = "META-REFRESH失败: response 为空"
            return False

        ip_safe2, ip_err2 = self._is_safe_ip(ip_addr2)
        if not ip_safe2:
            ctx.meta_follow_error = f"META-REFRESH拦截: {ip_err2}"
            try:
                response2.close()
            except Exception:
                pass
            return False

        # 切换到跳转后的响应
        ctx.meta_followed = True
        ctx.meta_note = f"[META-REFRESH] → {final_url2}"
        ctx.redirect_first_status = ctx.redirect_first_status or redirect_first_status2
        try:
            ctx.response.close()
        except Exception:
            pass
        ctx.response = response2
        ctx.final_url = final_url2
        ctx.ip_addr = ip_addr2
        ctx.response_headers = self._collect_response_headers(response2)

        # 重新判断内容类型
        ctx.content_type = ctx.response_headers.get('Content-Type', '').lower()
        ctx.is_text_content = any(t in ctx.content_type for t in ['html', 'text', 'xml', 'json', 'javascript'])
        if not ctx.is_text_content and ctx.content_type:
            self._handle_non_text_content(ctx)  # 内部会 raise _EarlyExit

        return True

    @staticmethod
    def _parse_meta_refresh(sample: bytes) -> Tuple[Optional[int], str]:
        # 从 HTML 片段中提取 meta refresh 的 (delay, url)。
        # 返回 (None, '') 表示未命中。
        try:
            text = sample.decode('latin1', errors='ignore')
        except Exception:
            return None, ''

        # 兼容：
        # <meta http-equiv="refresh" content="0; url=xxx">
        # <meta http-equiv="refresh" content="0; url='http://x'">
        # <META HTTP-EQUIV="REFRESH" CONTENT="0; URL=xxx">
        m = RegexCache.get('meta_refresh').search(text)
        if not m:
            return None, ''

        # 两种属性顺序各占 3 组: (1-3) http-equiv 在前, (4-6) content 在前
        try:
            delay = int(m.group(1) or m.group(4))
        except Exception:
            delay = None

        # 带引号的 url 和不带引号的 url 二选一，取匹配的那一侧
        target = (
            m.group(2) or m.group(3) or
            m.group(5) or m.group(6) or ''
        ).strip().strip("\"'")
        return delay, target

    def run(self) -> None:
        # 主执行线程：URL规范化 → HTTP请求 → 内容提取

        if self._is_cancelled:
            self.result_signal.emit(self.row, self.url, '', '', '', '', '已取消', '')
            return

        urls_to_try, original_has_scheme, prep_error = self._prepare_urls()
        if prep_error:
            self.result_signal.emit(self.row, self.url, '', '', '', '', _sanitize_error(prep_error), '')
            return

        headers = self._build_headers()

        last_error = ''
        last_emit_url = self.url  # 最终失败时 emit 的 URL，避免取到"带错误描述"的哨兵字符串
        for norm_url in urls_to_try:
            # 检查是否为错误信息（格式: "原始URL [错误描述]"）
            # 有效URL不含空格，空格+方括号组合可可靠识别错误标记
            if ' [' in norm_url and norm_url.endswith(']') and ' ' in norm_url:
                last_error = norm_url.split(' [', 1)[1][:-1]
                continue

            # 仅用于格式校验，不保留返回值
            try:
                urlparse(norm_url)
            except ValueError as e:
                last_error = f'URL解析失败: {e}'
                continue

            last_emit_url = norm_url

            if self._is_cancelled:
                self.result_signal.emit(self.row, self.url, '', '', '', '', '已取消', '')
                return

            is_safe, safety_error = self._is_safe_url(norm_url)
            if not is_safe:
                self.result_signal.emit(
                    self.row, norm_url, '', '', '', '',
                    _sanitize_error(f'安全拦截: {safety_error}'), ''
                )
                return

            try:
                ctx = _CheckContext(
                    norm_url=norm_url,
                    headers=headers,
                    start_time=time.monotonic(),
                )
                ctx.connect_timeout, ctx.read_timeout = self._compute_timeouts(
                    urls_to_try, original_has_scheme, norm_url
                )

                with requests.Session() as session:
                    self._connect_and_validate(ctx, session)
                    ctx.response_time = time.monotonic() - ctx.start_time
                    ctx.response_headers = self._collect_response_headers(ctx.response)
                    ctx.content_type = ctx.response_headers.get('Content-Type', '').lower()
                    ctx.is_text_content = any(
                        t in ctx.content_type for t in ['html', 'text', 'xml', 'json', 'javascript']
                    )

                    # 非文本内容 → _handle_non_text_content 内部 raise _EarlyExit
                    if not ctx.is_text_content and ctx.content_type:
                        self._handle_non_text_content(ctx)

                    # 文本内容：下载 + meta refresh 循环
                    try:
                        while True:
                            self._download_text_content(ctx)
                            if self._handle_meta_refresh(ctx, session):
                                continue
                            break

                        # 计算最终 content_length
                        if not ctx.size_exceeded:
                            declared = self._parse_content_length_header(ctx.response.headers)
                            display = declared if declared is not None else ctx.downloaded_size
                            ctx.content_length = self._format_size(display)
                        if ctx.capture_exceeded:
                            ctx.content_length += f' (已截取前{self.MAX_BODY_CAPTURE_SIZE / 1024:.0f}KB)'
                        ctx.response_time = time.monotonic() - ctx.start_time
                        ctx.content_length += f' ({ctx.response_time:.2f}s)'

                        # 解码 HTML
                        raw_bytes = bytes(ctx.captured)
                        ctx.html = self._decode_html_intelligently(
                            raw_bytes, ctx.response.encoding or 'utf-8'
                        )
                        if ctx.size_exceeded:
                            ctx.html = f'[警告: 超过{self.MAX_CONTENT_SIZE / (1024*1024):.0f}MB限制，已截断]\n\n' + ctx.html
                        elif ctx.capture_exceeded:
                            ctx.html = f'[提示: 仅保留前{self.MAX_BODY_CAPTURE_SIZE / 1024:.0f}KB内容用于预览/识别]\n\n' + ctx.html

                    except _EarlyExit:
                        raise
                    except Exception as content_e:
                        ctx.html = f'[内容获取失败: {str(content_e)}]'
                        ctx.content_length = f'0 bytes ({ctx.response_time:.2f}s)'

                    # 提取页面信息
                    try:
                        ctx.title, ctx.banner = self.extract_page_info(
                            ctx.html, ctx.response.encoding, ctx.response_headers, ctx.final_url
                        )
                    except Exception as info_e:
                        ctx.title, ctx.banner = '[信息提取失败]', f'[识别失败: {str(info_e)}]'

                    # 构建错误信息
                    ctx.error_msg = ''
                    ctx.error_msg = self._build_http_error(ctx.response.status_code)
                    if not ctx.error_msg:
                        ctx.error_msg = self._build_redirect_info(ctx)
                    if ctx.meta_follow_error:
                        ctx.error_msg = (ctx.error_msg + ' ' if ctx.error_msg else '') + ctx.meta_follow_error

                    self._emit_result(ctx)
                    return

            except _EarlyExit as e:
                # 对 _EarlyExit 的 8 元组里的 error 字段做脱敏再转发
                args = list(e.emit_args)
                if len(args) >= 7:
                    args[6] = _sanitize_error(args[6])
                self.result_signal.emit(*args)
                return
            # 异常分类处理（精确定位错误类型）
            except requests.exceptions.TooManyRedirects:
                self.result_signal.emit(self.row, norm_url, '', '', '', '',
                                      f'ERR_TOO_MANY_REDIRECTS (>{self.MAX_REDIRECTS}次)', '')
                return
            except requests.exceptions.SSLError as e:
                last_error = self._parse_ssl_error(e)
                continue
            except requests.exceptions.ConnectionError as e:
                last_error = self._parse_connection_error(e)
                continue
            except requests.exceptions.Timeout:
                last_error = (
                    f'请求超时 (连接≤{self.CONNECT_TIMEOUT}s, 读取≤{self.READ_TIMEOUT}s, '
                    f'总耗时≤{self.MAX_TOTAL_TIME}s)'
                )
                continue
            except requests.exceptions.HTTPError as e:
                last_error = f'HTTP错误: {str(e)}'
                continue
            except requests.exceptions.RequestException as e:
                last_error = self._parse_connection_error(e)
                continue
            except UnicodeDecodeError as e:
                last_error = f'内容编码错误: {e.encoding if hasattr(e, "encoding") else "unknown"}'
                continue
            except MemoryError:
                last_error = '内存不足: 响应过大'
                continue
            except KeyboardInterrupt:
                raise
            except (OSError, IOError) as e:
                last_error = f'IO错误: {str(e)}'
                continue
            except Exception as e:
                import traceback
                last_error = f'未知错误: {type(e).__name__}: {str(e)}'
                sanitized_url = sanitize_url_for_export(norm_url)
                logger.debug(f"URL检查异常 (row={self.row}, url={sanitized_url}):\n{traceback.format_exc()}")
                continue

        # 所有尝试均失败
        self.result_signal.emit(
            self.row, last_emit_url,
            '', '', '', '', _sanitize_error(last_error or '全部尝试失败'), ''
        )



    def _parse_ssl_error(self, e: Exception) -> str:
        # 解析SSL错误（8种常见SSL问题识别）
        error_str = str(e).lower()
        
        if 'certificate verify failed' in error_str:
            return 'SSL证书验证失败 (自签名或过期证书)'
        elif 'certificate has expired' in error_str:
            return 'SSL证书已过期'
        elif 'hostname mismatch' in error_str or 'doesn\'t match' in error_str:
            return 'SSL证书域名不匹配'
        elif 'ssl23_get_server_hello' in error_str:
            return 'SSL握手失败 (服务器不支持SSL/TLS)'
        elif 'ssl3_get_record' in error_str:
            return 'SSL协议错误'
        elif 'tlsv1 alert' in error_str:
            return 'TLS警报 (协议版本不兼容)'
        elif 'certificate_unknown' in error_str:
            return 'SSL证书未知或不受信任'
        elif 'handshake failure' in error_str:
            return 'SSL握手失败'
        else:
            return f'SSL/TLS错误: {str(e)[:100]}'
    
    def _parse_connection_error(self, e: Exception) -> str:
        # 解析连接错误（DNS、协议、拒绝等）
        error_str = str(e).lower()
        if "badstatusline" in error_str:
            if "pop3" in error_str:
                return 'Wrong Protocol (目标是POP3服务)'
            elif "smtp" in error_str:
                return 'Wrong Protocol (目标是SMTP服务)'
            else:
                return 'Wrong Protocol (非HTTP协议服务)'
        elif "wrong_principal" in error_str or "sec_e_wrong_principal" in error_str:
            return 'Certificate Error (证书主体名称不正确)'
        elif "unsafe port" in error_str or "unsafe_port" in error_str:
            return 'ERR_UNSAFE_PORT (不安全的端口)'
        elif "[winerror 10061]" in error_str or "connection refused" in error_str:
            return 'Connection refused (连接被拒绝)'
        elif "[winerror 10054]" in error_str or "connection reset" in error_str:
            return 'Connection reset (连接被重置)'
        elif '[errno 11001]' in error_str or 'name or service not known' in error_str:
            return 'DNS_PROBE_FINISHED_NXDOMAIN (域名无法解析)'
        elif 'max retries exceeded' in error_str:
            if 'failed to establish' in error_str:
                return 'Connection refused (无法建立连接)'
            else:
                return 'Max retries exceeded (超过最大重试次数)'
        elif isinstance(e, Timeout):
            return '连接超时 (Connection Timeout)'
        else:
            return f'连接错误: {str(e)}'

    @staticmethod
    def _collect_response_headers(response: requests.Response) -> Dict[str, str]:
        # requests 的 response.headers 会折叠/覆盖重复 header（如多个 Server）。
        # 这里尽量从底层 raw.headers 获取原始列表，并合并展示，提升识别准确性。
        merged: Dict[str, str] = {}
        try:
            for k, v in response.headers.items():
                merged[str(k)] = str(v)
        except Exception as e:
            logger.debug(f"响应头解析失败: {type(e).__name__}: {e}")
        raw = getattr(response, "raw", None)
        raw_headers = getattr(raw, "headers", None) if raw is not None else None

        def merge_multi(name: str) -> None:
            if raw_headers is None:
                return
            getlist = getattr(raw_headers, "getlist", None)
            if not callable(getlist):
                return
            try:
                values = [str(x).strip() for x in getlist(name) if str(x).strip()]
                if values:
                    merged[name] = "; ".join(values)
            except Exception as e:
                logger.debug(f"Header getlist({name}) 失败: {type(e).__name__}: {e}")

        # 常见可能重复/叠加的头
        for header_name in ("Server", "Via", "X-Powered-By"):
            merge_multi(header_name)

        return merged

    def extract_page_info(self, html, original_encoding='utf-8', response_headers=None, _current_url=''):
        return extract_html_page_info(
            html,
            original_encoding=original_encoding,
            response_headers=response_headers,
            _current_url=_current_url,
            framework_search_size=self.FRAMEWORK_SEARCH_SIZE,
            framework_patterns=self._FRAMEWORK_PATTERNS,
        )

    @staticmethod
    def _parse_html(html: str) -> '_HtmlHeadParser':
        return parse_html_head(html)

    def _decode_html_intelligently(self, html, original_encoding='utf-8'):
        return decode_html_content(
            html,
            original_encoding=original_encoding,
            encoding_detect_size=self.ENCODING_DETECT_SIZE,
        )

    def _extract_title(self, html, response_headers=None, parsed=None):
        return extract_html_title(html, response_headers=response_headers, parsed=parsed)

    def _extract_first_visible_text(self, html_sample):
        return extract_visible_text(html_sample)

    def _extract_banner(self, html, response_headers=None, parsed=None):
        return extract_banner_info(
            html,
            response_headers=response_headers,
            parsed=parsed,
            framework_search_size=self.FRAMEWORK_SEARCH_SIZE,
            framework_patterns=self._FRAMEWORK_PATTERNS,
        )
