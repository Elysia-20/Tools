# 用于优化模式匹配的正则表达式缓存

import re
from typing import Dict


class RegexCache:
    # 集中式正则表达式模式缓存，避免重复编译
    
    _compiled_patterns: Dict[str, re.Pattern] = {
        'charset': re.compile(r'<meta[^>]*charset=["\']?(.*?)["\']?[\s/>]', re.IGNORECASE),
        'charset_content': re.compile(r'<meta[^>]*content=["\'].*?charset=(.*?)["\']', re.IGNORECASE),
        'xml_encoding': re.compile(r'<\?xml[^>]*encoding=["\']?(.*?)["\']?[\s?]', re.IGNORECASE),
        'chinese': re.compile(r'[\u4e00-\u9fff]'),
        'english': re.compile(r'[a-zA-Z]'),
        'punctuation': re.compile(r'[,.!?，。！？]'),
        'garbled': re.compile(r'[\ufffd\u25a1]'),
        'html_tags': re.compile(r'<[^>]+>'),
        'whitespace': re.compile(r'\s+'),
        'control_chars': re.compile(r'[\x00-\x1f\x7f-\x9f]'),
        'strip_script': re.compile(r'<script[^>]*>[^<]*(?:<(?!/script>)[^<]*)*</script>', re.IGNORECASE | re.DOTALL),
        'strip_style': re.compile(r'<style[^>]*>[^<]*(?:<(?!/style>)[^<]*)*</style>', re.IGNORECASE | re.DOTALL),
        'strip_comment': re.compile(r'<!--[^-]*(?:-(?!->)[^-]*)*-->', re.DOTALL),
        'redirect_domain': re.compile(r'(?:https?://)?([^/]+)'),
        'meta_refresh': re.compile(
            # 同时兼容两种属性顺序和多种引号写法：
            # <meta http-equiv="refresh" content="0;url=x">
            # <meta content="0;url=x" http-equiv="refresh">
            r'<meta[^>]*'
            r'(?:'
            # 顺序1: http-equiv 在前，content 在后
            r'http-equiv\s*=\s*["\']?\s*refresh\s*["\']?[^>]*'
            r'content\s*=\s*["\']?\s*([0-9]+)\s*;\s*url\s*=\s*'
            r'(?:["\']\s*([^"\'>]+?)\s*["\']|([^"\'>\s]+))'
            r'|'
            # 顺序2: content 在前，http-equiv 在后
            r'content\s*=\s*["\']?\s*([0-9]+)\s*;\s*url\s*=\s*'
            r'(?:["\']\s*([^"\'>]+?)\s*["\']|([^"\'>\s]+))'
            r'[^>]*http-equiv\s*=\s*["\']?\s*refresh\s*["\']?'
            r')',
            re.IGNORECASE
        ),
    }
    
    @classmethod
    def get(cls, pattern_name: str) -> re.Pattern:
        # 根据名称获取已编译的正则表达式模式
        try:
            return cls._compiled_patterns[pattern_name]
        except KeyError:
            available = ', '.join(cls._compiled_patterns.keys())
            raise KeyError(f"未知的正则模式名: '{pattern_name}'，可用: {available}")
