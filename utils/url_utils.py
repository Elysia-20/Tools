# URL验证和规范化的工具函数

import ipaddress
from typing import List, Dict, Tuple, Optional
from urllib.parse import urlparse


# 危险端口黑名单 - 参考 Chrome/Chromium 的端口限制策略
# 来源: https://chromium.googlesource.com/chromium/src.git/+/refs/heads/main/net/base/port_util.cc
DANGEROUS_PORTS: Dict[int, str] = {
    1: 'tcpmux',
    7: 'Echo',
    9: 'Discard',
    11: 'Systat',
    13: 'Daytime',
    15: 'Netstat',
    17: 'QOTD',
    19: 'Chargen',
    20: 'FTP Data',
    21: 'FTP',
    22: 'SSH',
    23: 'Telnet',
    25: 'SMTP',
    37: 'Time',
    42: 'Name',
    43: 'Nicname',
    53: 'DNS',
    69: 'TFTP',
    77: 'RJE',
    79: 'Finger',
    87: 'Link',
    95: 'Supdup',
    101: 'Hostname',
    102: 'ISO-TSAP',
    103: 'GPPITNP',
    104: 'ACR-NEMA',
    109: 'POP2',
    110: 'POP3',
    111: 'Portmap/SunRPC',
    113: 'Auth/Ident',
    115: 'SFTP',
    117: 'UUCP Path',
    119: 'NNTP',
    123: 'NTP',
    135: 'MS RPC/EPMAP',
    137: 'NetBIOS NS',
    138: 'NetBIOS DGM',
    139: 'NetBIOS SSN',
    143: 'IMAP',
    161: 'SNMP',
    179: 'BGP',
    389: 'LDAP',
    427: 'SLP',
    465: 'SMTP+SSL',
    512: 'Exec',
    513: 'Login',
    514: 'Shell/Syslog',
    515: 'Printer',
    526: 'Tempo',
    530: 'Courier',
    531: 'Chat',
    532: 'Netnews',
    540: 'UUCP',
    548: 'AFP',
    554: 'RTSP',
    556: 'Remotefs',
    563: 'NNTP+SSL',
    587: 'SMTP',
    601: 'Syslog',
    636: 'LDAP+SSL',
    989: 'FTP+SSL',
    990: 'FTP+SSL',
    993: 'IMAP+SSL',
    995: 'POP3+SSL',
    1719: 'H323 Gatestat',
    1720: 'H323 Hostcall',
    1723: 'PPTP',
    2049: 'NFS',
    3659: 'Apple SASL',
    4045: 'Lockd',
    5060: 'SIP',
    5061: 'SIP+TLS',
    6000: 'X11',
    6566: 'SANE',
    6665: 'IRC',
    6666: 'IRC',
    6667: 'IRC',
    6668: 'IRC',
    6669: 'IRC',
    6697: 'IRC+TLS',
    10080: 'Amanda',
    # 常见数据库端口
    1433: 'MS SQL',
    1521: 'Oracle',
    3306: 'MySQL',
    5432: 'PostgreSQL',
    6379: 'Redis',
    9042: 'Cassandra',
    27017: 'MongoDB',
    27018: 'MongoDB',
    27019: 'MongoDB',
    28017: 'MongoDB',
    # 远程访问端口
    3389: 'RDP',
    5900: 'VNC',
    5901: 'VNC',
    5902: 'VNC',
    5903: 'VNC',
}


def read_urls_from_txt(file_path: str) -> List[str]:
    # 从文本文件读取URL，支持编码回退
    # Args:
    #   file_path: 文件路径
    # Returns:
    #   List[str]: URL列表（文件不存在或无权限时返回空列表）
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f if line.strip()]
    except UnicodeDecodeError:
        with open(file_path, 'r', encoding='gbk') as f:
            return [line.strip() for line in f if line.strip()]
    except (FileNotFoundError, PermissionError, OSError):
        return []


def is_port_dangerous(port: int) -> Tuple[bool, str]:
    # 检查端口是否在危险端口黑名单中
    # Args:
    #   port: 端口号
    # Returns:
    #   tuple[bool, str]: (是否危险, 服务名称)
    if port in DANGEROUS_PORTS:
        return True, DANGEROUS_PORTS[port]
    return False, ''


def normalize_url(url: str, allow_dangerous_ports: bool = False) -> Tuple[List[str], Optional[str]]:
    # 规范化URL并返回要尝试的URL列表
    # Args:
    #   url: 原始URL
    #   allow_dangerous_ports: 是否允许危险端口（默认False）
    # Returns:
    #   Tuple[List[str], Optional[str]]: (要尝试的URL列表, 错误信息)。
    #   校验失败时返回 ([], 错误信息)；成功时返回 (urls, None)。
    if not url or not url.strip():
        return [], '空URL'

    url = url.strip()

    # 提取端口号（用 urlparse 替代正则，正确处理 IPv6、路径等边界情况）
    to_parse = url if '://' in url else f'http://{url}'
    try:
        port_num = urlparse(to_parse).port
    except ValueError:
        return [], '无效端口号: 超出1-65535范围或格式错误'

    if port_num is not None:
        # 检查端口0（urlparse 对 >65535 已抛 ValueError，此处只需处理 0）
        if port_num == 0:
            return [], '无效端口号: 端口0不允许使用'

        # 检查危险端口（除非明确允许）
        if not allow_dangerous_ports:
            is_dangerous, service_name = is_port_dangerous(port_num)
            if is_dangerous:
                return [], f'不安全端口: {port_num} ({service_name}) 已被浏览器限制'

    # 返回规范化的URL（默认优先https，再回退http）
    # scheme 判断应大小写不敏感，兼容 HTTP://example.com
    # 对显式的非 http/https 协议直接报错，避免拼接出无效URL
    if '://' in url:
        scheme = urlparse(url).scheme.lower()
        if scheme in ('http', 'https'):
            return [url], None
        return [], f'不支持的协议: {scheme}'

    # 无 '://'：可能是裸域名/IP，或 host:port，也可能是 mailto:/tel: 这类无斜杠协议。
    # urlparse 会把 "example.com:8080" 的 "example.com" 误当作 scheme，因此不能只看
    # scheme 是否非空；冒号后是端口数字时视为 host:port（无 scheme），交给下面拼 https/http。
    raw_scheme = urlparse(url).scheme
    if raw_scheme and not url[len(raw_scheme) + 1:][:1].isdigit():
        return [], f'不支持的协议: {raw_scheme.lower()}'
    return [f'https://{url}', f'http://{url}'], None


def url_sort_key(text: str) -> Tuple[object, ...]:
    # URL/IP 智能排序 key：
    # - IP 按数值排序（避免 10.0.0.1 排在 2.0.0.1 前面的问题）
    # - 域名按 hostname（忽略大小写）再按端口/路径/查询排序
    # - 无法解析的行回退按整体字符串排序
    raw = (text or "").strip()
    if not raw:
        return (2, "")

    lower = raw.casefold()

    # 预处理：补协议便于解析（兼容 1.2.3.4:80/path、example.com 等）
    if lower.startswith("//"):
        to_parse = "http:" + raw
    elif "://" in raw:
        to_parse = raw
    else:
        to_parse = "http://" + raw

    parsed = urlparse(to_parse)
    try:
        host = (parsed.hostname or "").strip("[]")
    except ValueError:
        host = ""

    # 非法端口（如 example.com:abc）不应让排序崩溃
    try:
        port = parsed.port if parsed.port is not None else -1
    except ValueError:
        port = -1
    path = (parsed.path or "").casefold()
    query = (parsed.query or "").casefold()

    if host:
        try:
            ip_obj = ipaddress.ip_address(host)
            return (0, ip_obj.version, int(ip_obj), port, path, query, lower)
        except ValueError:
            return (1, host.casefold(), port, path, query, lower)

    return (2, lower)
