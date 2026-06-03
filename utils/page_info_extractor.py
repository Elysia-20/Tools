import re
from html.parser import HTMLParser
from typing import Optional

from .logger import get_logger
from .regex_cache import RegexCache

logger = get_logger('page_info_extractor')

DEFAULT_FRAMEWORK_PATTERNS = [
    (re.compile(r'wp-content|wordpress', re.IGNORECASE), 'WordPress'),
    (re.compile(r'drupal|Drupal\.settings', re.IGNORECASE), 'Drupal'),
    (re.compile(r'joomla|/components/com_', re.IGNORECASE), 'Joomla'),
    (re.compile(r'laravel|Laravel', re.IGNORECASE), 'Laravel'),
    (re.compile(r'thinkphp|think_template', re.IGNORECASE), 'ThinkPHP'),
    (re.compile(r'symfony', re.IGNORECASE), 'Symfony'),
    (re.compile(r'codeigniter', re.IGNORECASE), 'CodeIgniter'),
    (re.compile(r'vue\.js|vue@|__VUE__', re.IGNORECASE), 'Vue.js'),
    (re.compile(r'react|react-dom|__REACT', re.IGNORECASE), 'React'),
    (re.compile(r'angular|ng-|__ANGULAR__', re.IGNORECASE), 'Angular'),
    (re.compile(r'jquery-[\d.]+', re.IGNORECASE), 'jQuery'),
    (re.compile(r'bootstrap[.\-]\d', re.IGNORECASE), 'Bootstrap'),
    (re.compile(r'django', re.IGNORECASE), 'Django'),
    (re.compile(r'flask', re.IGNORECASE), 'Flask'),
    (re.compile(r'express', re.IGNORECASE), 'Express'),
    (re.compile(r'fastapi', re.IGNORECASE), 'FastAPI'),
    (re.compile(r'uwsgi', re.IGNORECASE), 'uWSGI'),
    (re.compile(r'gunicorn', re.IGNORECASE), 'Gunicorn'),
    (re.compile(r'nginx', re.IGNORECASE), 'Nginx'),
    (re.compile(r'apache(?!\s*tomcat)', re.IGNORECASE), 'Apache'),
    (re.compile(r'openresty', re.IGNORECASE), 'OpenResty'),
    (re.compile(r'tomcat|apache\s*tomcat', re.IGNORECASE), 'Tomcat'),
    (re.compile(r'weblogic', re.IGNORECASE), 'WebLogic'),
    (re.compile(r'jboss|wildfly', re.IGNORECASE), 'JBoss/WildFly'),
    (re.compile(r'jetty', re.IGNORECASE), 'Jetty'),
    (re.compile(r'iis', re.IGNORECASE), 'IIS'),
    (re.compile(r'next\.js|__NEXT_DATA__', re.IGNORECASE), 'Next.js'),
    (re.compile(r'nuxt|__NUXT__', re.IGNORECASE), 'Nuxt.js'),
    (re.compile(r'svelte', re.IGNORECASE), 'Svelte'),
    (re.compile(r'tailwind', re.IGNORECASE), 'Tailwind CSS'),
    (re.compile(r'vite', re.IGNORECASE), 'Vite'),
    (re.compile(r'webpack', re.IGNORECASE), 'Webpack'),
    (re.compile(r'spring', re.IGNORECASE), 'Spring'),
    (re.compile(r'servlet', re.IGNORECASE), 'Java Servlet'),
]


class HtmlHeadParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title: str = ''
        self.h1: str = ''
        self.meta_tags: list[dict] = []
        self._in_title = False
        self._in_h1 = False
        self._title_parts: list[str] = []
        self._h1_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag_name = tag.lower()
        if tag_name == 'title':
            self._in_title = True
            self._title_parts = []
        elif tag_name == 'h1' and not self.h1:
            self._in_h1 = True
            self._h1_parts = []
        elif tag_name == 'meta':
            self.meta_tags.append({key.lower(): (value or '') for key, value in attrs})

    def handle_endtag(self, tag):
        tag_name = tag.lower()
        if tag_name == 'title' and self._in_title:
            self._in_title = False
            if not self.title:
                self.title = ''.join(self._title_parts)
        elif tag_name == 'h1' and self._in_h1:
            self._in_h1 = False
            if not self.h1:
                self.h1 = ''.join(self._h1_parts)

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
        elif self._in_h1:
            self._h1_parts.append(data)

    def get_meta(self, *, name: str = '', prop: str = '', http_equiv: str = '') -> Optional[str]:
        for attrs in self.meta_tags:
            if name and attrs.get('name', '').lower() == name.lower():
                return attrs.get('content') or None
            if prop and attrs.get('property', '').lower() == prop.lower():
                return attrs.get('content') or None
            if http_equiv and attrs.get('http-equiv', '').lower() == http_equiv.lower():
                return attrs.get('content') or None
        return None


def parse_html(html) -> HtmlHeadParser:
    parser = HtmlHeadParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.debug(f"HTML parse failed: {type(exc).__name__}: {exc}")
    return parser


def decode_html_intelligently(html, original_encoding='utf-8', *, encoding_detect_size=1024):
    if isinstance(html, bytes):
        try:
            return html.decode('utf-8')
        except UnicodeDecodeError:
            pass

    if isinstance(html, bytes):
        search_sample = html[:encoding_detect_size].decode('ascii', errors='ignore')
    else:
        search_sample = str(html[:encoding_detect_size])

    declared_encoding = None
    for pattern_name in ('charset', 'charset_content', 'xml_encoding'):
        match = RegexCache.get(pattern_name).search(search_sample)
        if match:
            declared_encoding = match.group(1).lower()
            break

    encodings_to_try = []
    if original_encoding and original_encoding != 'utf-8':
        encodings_to_try.append(original_encoding)
    if declared_encoding:
        encodings_to_try.append(declared_encoding)

    common_encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'latin1', 'utf-16']
    encodings_to_try.extend(encoding for encoding in common_encodings if encoding not in encodings_to_try)

    best_decoded = None
    max_score = 0

    skip_utf16 = False
    if isinstance(html, bytes) and len(html) >= 2:
        skip_utf16 = html[0:2] not in (b'\xff\xfe', b'\xfe\xff') and html[1:2] != b'\x00'

    for encoding in encodings_to_try:
        if skip_utf16 and 'utf16' in encoding.lower().replace('-', ''):
            continue
        try:
            if isinstance(html, str):
                sample = html[:encoding_detect_size]
                if original_encoding and original_encoding != encoding:
                    test_decoded = sample.encode(original_encoding or 'utf-8', errors='ignore').decode(
                        encoding, errors='ignore'
                    )
                else:
                    test_decoded = sample
            else:
                sample = html[:encoding_detect_size]
                test_decoded = sample.decode(encoding, errors='ignore')

            score = 0
            if RegexCache.get('chinese').search(test_decoded):
                score += 3
            if RegexCache.get('english').search(test_decoded):
                score += 2
            if RegexCache.get('punctuation').search(test_decoded):
                score += 1
            if not RegexCache.get('garbled').search(test_decoded):
                score += 2

            if score > max_score:
                max_score = score
                if isinstance(html, str):
                    if original_encoding and original_encoding != encoding:
                        best_decoded = html.encode(original_encoding or 'utf-8', errors='ignore').decode(
                            encoding, errors='ignore'
                        )
                    else:
                        best_decoded = html
                else:
                    best_decoded = html.decode(encoding, errors='ignore')
        except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
            continue

    if best_decoded:
        return best_decoded
    if isinstance(html, bytes):
        return html.decode('utf-8', errors='ignore')
    return html


class _SpaDetector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_spa_root = False
        self.has_scripts = False
        self._body_depth = 0
        self._visible_text = []

    def handle_starttag(self, tag, attrs):
        tag_l = tag.lower()
        if tag_l == 'script':
            self.has_scripts = True
            return
        if tag_l == 'body':
            self._body_depth += 1
            return
        if self._body_depth > 0 and tag_l in ('div', 'section', 'main'):
            attrs_d = {k.lower(): (v or '') for k, v in attrs}
            el_id = attrs_d.get('id', '')
            if el_id in ('root', 'app', 'main') or (
                el_id.startswith(('root-', 'app-')) and len(el_id) > 5
            ):
                self.has_spa_root = True

    def handle_endtag(self, tag):
        if tag.lower() == 'body' and self._body_depth > 0:
            self._body_depth -= 1

    def handle_data(self, data):
        if self._body_depth > 0:
            self._visible_text.append(data)

    @property
    def has_visible_text(self):
        text = ''.join(self._visible_text).strip()
        return bool(text)


def detect_spa_framework(html):
    detector = _SpaDetector()
    try:
        detector.feed(html)
    except Exception:
        pass
    if detector.has_scripts and not detector.has_visible_text:
        if detector.has_spa_root:
            return '[SPA动态页面]'
    return None


def extract_first_visible_text(html_sample, *, max_length=50):
    text = RegexCache.get('strip_script').sub('', html_sample)
    text = RegexCache.get('strip_style').sub('', text)
    text = RegexCache.get('strip_comment').sub('', text)
    text = RegexCache.get('html_tags').sub(' ', text)
    text = RegexCache.get('whitespace').sub(' ', text).strip()
    if len(text) > max_length:
        text = text[:max_length] + '...'
    return text if text else ''


def extract_title(html, response_headers=None, parsed=None):
    if parsed is None:
        parsed = parse_html(html)

    title_candidates = []
    if parsed.title:
        title_candidates.append(parsed.title)

    meta_title = parsed.get_meta(name='title')
    if meta_title:
        title_candidates.append(meta_title)
    og_title = parsed.get_meta(prop='og:title')
    if og_title:
        title_candidates.append(og_title)
    if parsed.h1:
        title_candidates.append(parsed.h1)

    for candidate in title_candidates:
        cleaned = RegexCache.get('html_tags').sub('', candidate)
        cleaned = RegexCache.get('whitespace').sub(' ', cleaned.strip())
        cleaned = RegexCache.get('control_chars').sub('', cleaned)
        if cleaned:
            return cleaned

    spa_title = detect_spa_framework(html[:8192])
    if spa_title:
        return spa_title

    body_text = extract_first_visible_text(html[:2048])
    if body_text:
        return f'[{body_text}]'

    if response_headers:
        location = response_headers.get('Location', '')
        if location:
            domain_match = RegexCache.get('redirect_domain').search(location)
            if domain_match:
                return f'[重定向到: {domain_match.group(1)}]'

        if 'Content-Type' in response_headers:
            content_type = response_headers['Content-Type'].lower()
            if 'json' in content_type:
                return '[JSON API 接口]'
            if 'xml' in content_type:
                return '[XML 接口]'
            if 'image' in content_type:
                return '[图片资源]'
            if 'text/plain' in content_type:
                return '[纯文本文件]'
            if 'application/octet-stream' in content_type:
                return '[二进制文件]'
            return f'[{content_type.split("/")[0].upper()} 内容]'

        if 'Server' in response_headers:
            return f"[{response_headers['Server']} 服务器]"

    return '[无标题页面]'


def extract_banner(
    html,
    response_headers=None,
    parsed=None,
    *,
    framework_search_size=50000,
    framework_patterns=None,
):
    banner_info = []

    if response_headers:
        important_headers = {
            'Server': 'Server',
            'X-Powered-By': 'Powered By',
            'X-Generator': 'Generator',
            'X-Framework': 'Framework',
            'X-AspNet-Version': 'ASP.NET',
            'X-Runtime': 'Runtime',
            'Via': 'Via',
            'CF-Ray': 'Cloudflare',
            'X-CDN': 'CDN',
        }

        for header, label in important_headers.items():
            if header in response_headers:
                value = response_headers.get(header, '').strip()
                if value:
                    banner_info.append(f'{label}: {value}')

        set_cookie = response_headers.get('Set-Cookie', '') or ''
        cookie_clues = []
        clue_map = {
            'PHPSESSID': 'PHP',
            'JSESSIONID': 'Java',
            'ASP.NET_SessionId': 'ASP.NET',
            'laravel_session': 'Laravel',
            'sid=': 'Session',
            'csrftoken': 'Django',
            'symfony': 'Symfony',
            'weblogic': 'WebLogic',
        }
        for key, label in clue_map.items():
            if key.lower() in set_cookie.lower():
                cookie_clues.append(label)
        if cookie_clues:
            banner_info.append(f"Cookie: {', '.join(sorted(set(cookie_clues)))}")

    if parsed is None:
        parsed = parse_html(html[:framework_search_size])

    generator = parsed.get_meta(name='generator') or parsed.get_meta(prop='generator')
    if generator:
        banner_info.append(generator)
    app_name = parsed.get_meta(name='application-name')
    if app_name:
        banner_info.append(app_name)
    framework_meta = parsed.get_meta(name='framework')
    if framework_meta:
        banner_info.append(framework_meta)

    if framework_patterns is None:
        framework_patterns = DEFAULT_FRAMEWORK_PATTERNS

    search_area = html[:framework_search_size]
    detected_frameworks = set()
    for compiled_re, name in framework_patterns:
        if compiled_re.search(search_area):
            detected_frameworks.add(name)

    if detected_frameworks:
        banner_info.append(' | '.join(sorted(detected_frameworks)))

    return ' | '.join(banner_info) if banner_info else '[无标识信息]'


def extract_page_info(
    html,
    original_encoding='utf-8',
    response_headers=None,
    _current_url='',
    *,
    framework_search_size=50000,
    framework_patterns=None,
):
    title = ''
    banner = ''
    parsed = HtmlHeadParser()

    try:
        parsed = parse_html(html)
        title = extract_title(html, response_headers, parsed)
    except Exception as exc:
        title = f'[解码失败: {exc}]'

    try:
        banner = extract_banner(
            html,
            response_headers,
            parsed,
            framework_search_size=framework_search_size,
            framework_patterns=framework_patterns,
        )
    except Exception as exc:
        banner = f'[识别失败: {exc}]'

    return title or '[无标题页面]', banner
