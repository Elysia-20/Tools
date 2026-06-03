import logging
import sys
import traceback
from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.main_window import IntegratedSecurityTool
from utils import QtLogBus, QtLogHandler
from utils.logger import get_logger


_logger = get_logger('main')


def _qt_excepthook(exc_type, exc_value, exc_tb):
    # 全局未捕获异常处理：避免 Qt 默认行为（仅打印 stderr 后继续运行，
    # 容易掩盖 slot 中的 bug）。这里同时打日志并提示用户。
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    tb_text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _logger.error(f"未捕获异常:\n{tb_text}")
    try:
        QMessageBox.critical(
            None,
            "运行时错误",
            f"发生未捕获异常：\n\n{exc_type.__name__}: {exc_value}\n\n详细堆栈已写入日志/控制台。",
        )
    except Exception:
        # 弹窗失败（无 QApplication 等）就只打印
        sys.__excepthook__(exc_type, exc_value, exc_tb)


def _install_qt_log_handler() -> tuple[QtLogBus, QtLogHandler]:
    # 创建 Qt 日志总线 + handler，挂到根 logger
    # 各模块的命名 logger（默认 propagate=True）→ 根 logger → QtLogHandler → bus
    # 这样不影响现有 stderr 输出，只是额外多一份送到 UI
    bus = QtLogBus()
    handler = QtLogHandler(bus, level=logging.DEBUG)
    root = logging.getLogger()
    # 根 logger 默认 level=WARNING，会丢弃命名 logger 上的 DEBUG/INFO 记录。
    # 把根 level 调到 DEBUG，但不影响命名 logger 上各自的 level/handler。
    if root.level > logging.DEBUG or root.level == logging.NOTSET:
        root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    return bus, handler


def main():
    # 应用程序的主入口点
    app = QApplication(sys.argv)
    app.setApplicationName('Integrated Security Tool')
    app.setOrganizationName('Security Tools')

    # 安装全局异常钩子（必须在 QApplication 创建后，使弹窗可用）
    sys.excepthook = _qt_excepthook

    # 安装 Qt 日志 handler，让 UI 能看到所有 logger 输出
    log_bus, log_handler = _install_qt_log_handler()

    try:
        window = IntegratedSecurityTool(log_bus=log_bus, log_handler=log_handler)
        window.show()
    except Exception:
        traceback.print_exc()
        QMessageBox.critical(None, "启动失败", f"应用程序初始化失败：\n{traceback.format_exc()}")
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
