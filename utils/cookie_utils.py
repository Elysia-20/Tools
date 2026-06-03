# Cookie 验证和清理工具函数

import re
from typing import Optional, Tuple

from utils.logger import get_logger

logger = get_logger('cookie_utils')


# Cookie 合法字符正则（模块级常量，避免每次调用重新编译）
# 包含 RFC 6265 允许的反斜杠 \，避免误判合法 cookie 值
_COOKIE_PATTERN = re.compile(
    r'^[\w\-\.=;\s:\/\%\+\~\(\)\@\#\$\&\*\!\'\"\|\,\?\[\]\{\}\<\>\`\^\\]+$',
    re.ASCII
)


def validate_cookie(cookie_str: str) -> Tuple[bool, str, str]:
    # 验证和清理 Cookie 字符串
    # Args:
    #   cookie_str: 原始 Cookie 字符串
    # Returns:
    #   tuple[bool, str, str]: (是否有效, 清理后的Cookie, 错误信息)
    if not cookie_str:
        return True, '', ''
    
    # 1. 检查换行符注入（CRLF注入攻击）
    if '\r' in cookie_str or '\n' in cookie_str:
        return False, '', 'Cookie 包含非法换行符（可能是注入攻击）'
    
    # 2. 检查 NULL 字节
    if '\x00' in cookie_str:
        return False, '', 'Cookie 包含 NULL 字节'
    
    # 3. 检查长度限制（浏览器限制通常为 4KB）
    if len(cookie_str) > 4096:
        return False, '', f'Cookie 过长（{len(cookie_str)} 字节，限制 4096）'
    
    # 4. 验证格式：key=value; key2=value2
    # 允许的字符：字母、数字、下划线、连字符、点、斜杠、冒号等常见字符
    # 以及 URL 编码（%xx）、加号、波浪号、圆括号等 cookie 中常见的字符
    # 但排除控制字符和危险字符（换行、NULL 已在前面检查）
    if not _COOKIE_PATTERN.match(cookie_str):
        return False, '', 'Cookie 格式无效（包含非法字符）'
    
    # 5. 验证每个 cookie 项的格式
    parts = cookie_str.split(';')
    cleaned_parts = []
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        # 每个部分应该是 key=value 格式
        if '=' not in part:
            return False, '', f'Cookie 格式错误："{part}" 缺少等号'
        
        key, value = part.split('=', 1)
        key = key.strip()
        value = value.strip()
        
        # 验证 key
        if not key:
            return False, '', 'Cookie 键不能为空'
        
        # Key 应该只包含字母、数字、下划线、连字符、点号（RFC 6265 允许点号）
        if not re.match(r'^[\w\-\.]+$', key, re.ASCII):
            return False, '', f'Cookie 键 "{key}" 包含非法字符'
        
        # Value 可以为空，但如果不为空应该是合法字符
        if value:
            # Value 可以包含更多字符，但不能有控制字符
            if re.search(r'[\x00-\x1f\x7f]', value):
                return False, '', f'Cookie 值 "{value}" 包含控制字符'
        
        cleaned_parts.append(f'{key}={value}')
    
    if not cleaned_parts:
        return False, '', 'Cookie 为空或格式完全错误'
    
    # 6. 重新组合清理后的 Cookie
    cleaned_cookie = '; '.join(cleaned_parts)
    
    return True, cleaned_cookie, ''


def sanitize_cookie(cookie_str: str) -> str:
    # 清理 Cookie 字符串（移除危险字符）
    # Args:
    #   cookie_str: 原始 Cookie 字符串
    # Returns:
    #   str: 清理后的 Cookie 字符串
    is_valid, cleaned, error = validate_cookie(cookie_str)
    
    if is_valid:
        return cleaned
    else:
        logger.warning(f"Cookie 验证失败: {error}")
        return ''


def get_cookie_warning(cookie_str: str) -> Optional[str]:
    # 获取 Cookie 警告信息（如果有的话）
    # Args:
    #   cookie_str: Cookie 字符串
    # Returns:
    #   Optional[str]: 警告信息，如果没有问题则返回 None
    if not cookie_str:
        return None
    
    warnings = []
    
    # 检查长度
    if len(cookie_str) > 3072:  # 警告阈值：3KB
        warnings.append(f'Cookie 较长（{len(cookie_str)} 字节），可能被某些服务器拒绝')
    
    # 检查 cookie 数量
    cookie_count = len([p for p in cookie_str.split(';') if p.strip()])
    if cookie_count > 50:
        warnings.append(f'Cookie 数量较多（{cookie_count} 个），可能影响性能')
    
    return '; '.join(warnings) if warnings else None
