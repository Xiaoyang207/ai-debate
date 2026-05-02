"""
应用程序入口点。

该模块负责初始化日志配置，并启动 Tkinter 主循环。
"""

from __future__ import annotations

import logging
import tkinter as tk

from ui import DebateApp

def setup_logging() -> None:
    """配置全局日志：控制台输出，级别 DEBUG。"""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    # 避免重复添加 handler
    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(ch)

if __name__ == "__main__":
    setup_logging()
    root = tk.Tk()
    app = DebateApp(root)
    root.mainloop()