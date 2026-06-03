import ipaddress
import socket
from typing import Optional
from urllib.parse import urlparse


def validate_ip_object(ip: 'ipaddress.IPv4Address | ipaddress.IPv6Address', label: str, *, allow_internal: bool) -> tuple[bool, str]:
    if ip.is_unspecified:
        return False, f"禁止访问未指定地址: {label}"
    if ip.is_private and not allow_internal:
        return False, f"禁止访问内网地址: {label}"
    if ip.is_reserved:
        return False, f"禁止访问保留地址: {label}"
    if ip.is_loopback and not allow_internal:
        return False, f"禁止访问回环地址: {label}"
    if str(ip) == "169.254.169.254":
        return False, "禁止访问云平台元数据服务"
    if ip.is_link_local:
        return False, f"禁止访问链路本地地址: {label}"
    if ip.is_multicast:
        return False, f"禁止访问组播地址: {label}"
    return True, ""


def is_safe_ip(ip_str: str, *, allow_internal: bool, logger=None) -> tuple[bool, str]:
    # 空字符串/解析失败一律拒绝（旧实现的"保守放行"会导致 SSRF 绕过）
    clean = (ip_str or "").strip()
    if not clean:
        return False, "IP 地址为空，拒绝放行"
    if clean.startswith('[') and clean.endswith(']'):
        clean = clean[1:-1]
    if '%' in clean:
        clean = clean.split('%', 1)[0]

    try:
        ip = ipaddress.ip_address(clean)
    except ValueError:
        if logger is not None:
            logger.debug(f"IP地址解析失败: {ip_str!r}")
        return False, f"IP 地址格式非法: {ip_str!r}"

    return validate_ip_object(ip, clean, allow_internal=allow_internal)


def _resolve_hostname_ips(hostname: str) -> list[str]:
    # 返回 hostname 解析出的去重 IP 列表。失败返回空列表。
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    ips: list[str] = []
    seen: set[str] = set()
    for info in infos:
        try:
            ip = info[4][0]
        except (IndexError, TypeError):
            continue
        if ip and ip not in seen:
            seen.add(ip)
            ips.append(ip)
    return ips


def is_safe_url(url: str, *, allow_internal: bool, dangerous_ports: Optional[dict[int, str]] = None) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, f"URL安全检查失败: {exc}"

    hostname = parsed.hostname
    if not hostname:
        return False, "无效的主机名"

    try:
        port = parsed.port
    except ValueError as exc:
        return False, f"无效端口: {exc}"
    if port == 0:
        return False, "无效端口: 端口0不允许使用"
    if port is None:
        port = 443 if parsed.scheme == 'https' else 80

    dangerous_ports = dangerous_ports or {}
    if port in dangerous_ports:
        service_name = dangerous_ports[port]
        return False, f"禁止访问危险端口: {port} ({service_name})"

    # hostname 本身就是 IP 字面量，直接校验
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None

    if ip is not None:
        safe, reason = validate_ip_object(ip, hostname, allow_internal=allow_internal)
        if not safe:
            return False, reason
    else:
        # 域名：拒绝明显的本机标记（防止走 /etc/hosts 等劫持）
        dangerous_hosts = ('localhost', 'localhost.localdomain', '0.0.0.0')
        if (not allow_internal) and hostname.lower() in dangerous_hosts:
            return False, f"禁止访问本地主机: {hostname}"

        # DNS 预解析 —— 这是防 SSRF 的核心。不做预解析就会被
        # DNS rebinding / 指向内网的公网域名直接绕过。
        resolved = _resolve_hostname_ips(hostname)
        if not resolved:
            # fail-closed：解析不出来时直接拒绝。允许放行会让攻击者通过临时 DNS
            # 失败 + requests 内部不同的解析路径绕过 SSRF 检查。
            return False, f"无法解析主机: {hostname}（拒绝放行）"
        for ip_str in resolved:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                return False, f"域名解析异常 IP: {ip_str}"
            safe, reason = validate_ip_object(ip_obj, ip_str, allow_internal=allow_internal)
            if not safe:
                return False, f"{hostname} → {reason}"

    return True, ""
