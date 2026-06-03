# 统一日志管理模块

import logging
import logging.handlers
import sys
from typing import Optional


def setup_logger(
    name: str = 'tools',
    level: int = logging.DEBUG,
    log_file: Optional[str] = None
) -> logging.Logger:
    # 创建并配置日志记录器

    # Args:
    #     name: 日志记录器名称
    #     level: 日志级别
    #     log_file: 可选的日志文件路径

    # Returns:
    #     配置好的Logger实例
    logger = logging.getLogger(name)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 日志格式
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台输出
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件输出（可选，自动轮转：单文件最大5MB，保留3个备份）
    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = 'tools') -> logging.Logger:
    # 获取日志记录器（内部已有 handler 去重）
    return setup_logger(name)
