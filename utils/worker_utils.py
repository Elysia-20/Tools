# QThread Worker 安全释放工具


def safe_dispose_worker(worker):
    # 安全释放旧的 QThread worker：断开信号、取消、延迟删除
    if worker is None:
        return
    # 通过 MRO 遍历所有基类，收集 pyqtSignal 属性名
    signal_names = set()
    for klass in type(worker).__mro__:
        for name, val in vars(klass).items():
            type_name = type(val).__name__
            if type_name == 'pyqtSignal':
                signal_names.add(name)
    # 保底：确保常见信号都在列表中
    signal_names.update(('result_ready', 'error', 'finished', 'progress'))
    for sig_name in signal_names:
        try:
            getattr(worker, sig_name).disconnect()
        except (TypeError, RuntimeError, AttributeError):
            pass
    if getattr(worker, "isRunning", lambda: False)():
        try:
            worker.cancel()
        except (AttributeError, Exception):
            pass
    # 先连 deleteLater 再判断 isFinished，避免 race window：
    # 如果 worker 在 isFinished()→connect 之间结束，finished 信号已发完，
    # 后续 connect 注册的槽永远不会触发，QObject 泄漏。
    # deleteLater 是幂等的（Qt 内部去重），先 connect 再额外调用是安全的。
    try:
        worker.finished.connect(worker.deleteLater)
    except (RuntimeError, TypeError):
        pass
    try:
        if worker.isFinished():
            worker.deleteLater()
    except RuntimeError:
        pass
