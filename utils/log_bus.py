# Qt 日志总线：把 logging 模块的输出转发到 Qt 信号，供 UI 标签页消费。
#
# 设计要点：
# - QtLogHandler 继承 logging.Handler，emit() 可被任意线程调用
# - QtLogBus 是 QObject，提供 pyqtSignal 让 emit 跨线程到 UI 主线程
# - 自动脱敏消息中的 URL（防止 token/key/password 泄漏到 UI）
# - 不影响现有 stderr 输出（双向并存）

import logging
from datetime import datetime

from PyQt6.QtCore import QObject, pyqtSignal


class QtLogBus(QObject):
    # 把 logging 记录广播给 UI。
    # 线程安全：record_emitted.emit() 可从任意线程调用，
    # Qt 自动用 queued connection 把信号送到 main thread 的槽。
    record_emitted = pyqtSignal(str, str, str, str)
    # 信号参数: (level_name, logger_name, message, timestamp_str)


class QtLogHandler(logging.Handler):
    # 把 LogRecord 转发到 QtLogBus 信号。
    # 自动脱敏消息中的 URL（复用 url_worker._sanitize_error）。

    def __init__(self, bus: QtLogBus, level: int = logging.DEBUG) -> None:
        super().__init__(level)
        self._bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            # exc_info 携带异常 traceback，也放进消息体
            if record.exc_info:
                formatter = self.formatter or logging.Formatter()
                msg = msg + '\n' + formatter.formatException(record.exc_info)

            # 脱敏：lazy import 避免 utils ↔ workers 循环依赖
            try:
                from workers.url_worker import _sanitize_error
                msg = _sanitize_error(msg)
            except Exception:
                # 脱敏不能让日志整个失效；万一脱敏函数自身出错，照原样发
                pass

            timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S.%f')[:-3]
            self._bus.record_emitted.emit(
                record.levelname,
                record.name,
                msg,
                timestamp,
            )
        except Exception:
            # logging.Handler 不允许抛异常
            self.handleError(record)
