"""
Tkinter 图形用户界面。

该模块实现了完整的辩论应用 UI，完全通过回调与引擎交互，
不含任何核心辩论逻辑，便于更换界面框架。
"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Dict, List, Optional

from models import (
    AppConfig,
    DebateConfig,
    PRESET_TOPICS,
    STAGE_DEFS,
    THEMES,
)
from debate_engine import DebateEngine
from export import export_to_markdown, export_to_json, generate_debate_summary

logger = logging.getLogger("debate_ui")

# -----------------------------------------------------------------------------
# 常量
# -----------------------------------------------------------------------------
MAX_CHAT_LINES: int = 4000        # 聊天区显示上限行数
CHAT_TRIM_LINES: int = 1500       # 超出上限时保留的行数
MAX_HISTORY_ITEMS: int = 5000     # 历史记录最大条数
UI_REFRESH_MS: int = 150          # 消息队列轮询间隔（毫秒）

# 聊天区富文本标签配置
TEXT_TAG_CONFIGS: Dict[str, Dict[str, Any]] = {
    'topic_label': {'foreground': '#f59e0b', 'font': ('微软雅黑', 10, 'bold'), 'spacing1': 10, 'justify': 'center'},
    'topic': {'foreground': '#fbbf24', 'font': ('微软雅黑', 16, 'bold'), 'justify': 'center', 'spacing3': 5},
    'stage_header': {'foreground': '#a78bfa', 'font': ('微软雅黑', 13, 'bold'), 'justify': 'center', 'spacing1': 15, 'spacing3': 8},
    'pro_label': {'foreground': '#3b82f6', 'font': ('微软雅黑', 10, 'bold'), 'spacing1': 12},
    'con_label': {'foreground': '#ef4444', 'font': ('微软雅黑', 10, 'bold'), 'spacing1': 12, 'justify': 'right'},
    'pro_text': {'foreground': '#bfdbfe', 'lmargin1': 20, 'lmargin2': 20, 'spacing3': 8, 'font': ('微软雅黑', 11)},
    'con_text': {'foreground': '#fecaca', 'rmargin': 20, 'justify': 'right', 'spacing3': 8, 'font': ('微软雅黑', 11)},
    'end': {'foreground': '#f59e0b', 'font': ('微软雅黑', 14, 'bold'), 'justify': 'center', 'spacing1': 20, 'spacing3': 10},
    'divider': {'foreground': '#334155'},
    'info': {'foreground': '#64748b', 'font': ('微软雅黑', 9), 'justify': 'center', 'spacing3': 3},
}


# -----------------------------------------------------------------------------
# 主应用类
# -----------------------------------------------------------------------------

class DebateApp:
    """辩论赛图形界面，管理所有 UI 组件、用户交互及引擎控制。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("AI 辩论赛 · 全面增强版")
        self.root.minsize(800, 600)

        # 加载可持久化配置
        self.app_config = AppConfig()
        self.app_config.load()
        self.current_theme: str = self.app_config.get("theme", "暗色")
        self.font_size: int = self.app_config.get("font_size", 11)
        self.theme_colors = THEMES[self.current_theme]

        # 线程安全的消息队列（引擎 -> UI）
        self.event_queue: queue.Queue = queue.Queue()
        # 历史记录（UI 线程访问，无竞争）
        self.history: List[Dict[str, Any]] = []

        # 环节 Spinbox 存储（key 为 stageN）
        self.stage_spinboxes: Dict[str, tk.Spinbox] = {}

        # UI 状态
        self.is_running: bool = False
        self.is_paused: bool = False
        self._closing: bool = False

        # 辩论引擎引用
        self.engine: Optional[DebateEngine] = None

        # 进度统计（UI 线程更新）
        self.total_speeches: int = 0
        self.completed_speeches: int = 0
        self.start_time: Optional[float] = None

        # 构建界面
        self._build_ui()
        self._apply_theme()
        self.root.geometry(self.app_config.get("geometry", "1050x850"))
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # =====================================================================
    # 窗口生命周期
    # =====================================================================

    def on_closing(self) -> None:
        """窗口关闭清理：取消引擎，等待线程，保存配置并销毁。"""
        self._closing = True
        self._stop_engine()
        try:
            geometry = self.root.geometry()
        except Exception:
            geometry = "1050x850"
        self.app_config.set("geometry", geometry)
        self.app_config.set("theme", self.current_theme)
        self.app_config.set("font_size", self.font_size)
        self.app_config.save()
        self.root.destroy()

    def _stop_engine(self) -> None:
        """安全停止辩论引擎。"""
        if self.engine is not None:
            self.engine.cancel()
            self.engine.join(timeout=5.0)  # 最多等5秒
        self.is_running = False
        self.is_paused = False

    # =====================================================================
    # 主题与样式
    # =====================================================================

    def _apply_theme(self) -> None:
        """将当前主题颜色应用到所有组件。"""
        colors = THEMES[self.current_theme]
        self.root.configure(bg=colors["bg_main"])
        self._update_widget_colors(self.root, colors)
        self._update_button_colors()

    def _update_widget_colors(self, parent: tk.Widget, colors: dict) -> None:
        """递归更新组件及其子组件的背景/前景色。"""
        for child in parent.winfo_children():
            try:
                if isinstance(child, (tk.Frame, tk.Canvas)):
                    child.configure(bg=colors.get("bg_panel", colors["bg_main"]))
                elif isinstance(child, tk.Label):
                    child.configure(bg=colors["bg_panel"], fg=colors["fg_label"])
                elif isinstance(child, tk.Entry):
                    child.configure(bg=colors["bg_entry"], fg=colors["fg_entry"],
                                    insertbackground=colors["fg_entry"])
                elif isinstance(child, scrolledtext.ScrolledText):
                    child.configure(bg=colors["bg_entry"], fg=colors["fg_entry"])
            except tk.TclError:
                pass
            self._update_widget_colors(child, colors)

    def _update_button_colors(self) -> None:
        """更新特殊按钮颜色（因 Tk 限制无法通过递归设置）。"""
        colors = self.theme_colors
        if hasattr(self, 'start_btn'):
            if not self.is_running:
                self.start_btn.configure(bg=colors["btn_bg"], fg=colors["btn_fg"])
            else:
                self.start_btn.configure(bg=colors["btn_disabled_bg"])
        for btn in ('pause_btn', 'stop_btn', 'export_btn', 'import_btn'):
            try:
                btn_obj = getattr(self, btn)
                btn_obj.configure(bg=colors["btn_secondary_bg"], fg=colors["btn_secondary_fg"])
            except Exception:
                pass

    def toggle_theme(self, theme_name: str) -> None:
        """切换主题（暗色/亮色）。"""
        if theme_name == self.current_theme:
            return
        self.current_theme = theme_name
        self._apply_theme()

    # =====================================================================
    # UI 构建（主布局）
    # =====================================================================

    def _build_ui(self) -> None:
        """搭建整体界面：标题、左侧设置面板（可滚动）、右侧聊天区。"""
        colors = self.theme_colors
        main = tk.Frame(self.root, bg=colors["bg_main"])
        main.pack(fill='both', expand=True, padx=10, pady=10)

        # 标题
        title_frame = tk.Frame(main, bg=colors["bg_main"])
        title_frame.pack(fill='x', pady=(0, 10))
        tk.Label(title_frame, text="⚔️  AI 辩论赛 · 完整赛制",
                 font=('微软雅黑', 24, 'bold'), fg=colors["fg_title"], bg=colors["bg_main"]).pack()
        tk.Label(title_frame, text="正方：一辩→二辩→三辩→四辩  vs  反方：一辩→二辩→三辩→四辩",
                 font=('微软雅黑', 10), fg=colors["fg_sec"], bg=colors["bg_main"]).pack(pady=(2, 0))

        content = tk.Frame(main, bg=colors["bg_main"])
        content.pack(fill='both', expand=True)

        # 左侧可滚动设置面板
        left_panel = tk.Frame(content, bg=colors["bg_panel"], width=380)
        left_panel.pack(side='left', fill='y', padx=(0, 8))
        left_panel.pack_propagate(False)

        left_canvas = tk.Canvas(left_panel, bg=colors["bg_panel"], highlightthickness=0, width=360)
        left_scroll = tk.Scrollbar(left_panel, orient='vertical', command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_inner = tk.Frame(left_canvas, bg=colors["bg_panel"])
        left_inner.bind('<Configure>', lambda e: left_canvas.configure(scrollregion=left_canvas.bbox('all')))
        left_canvas.create_window((0, 0), window=left_inner, anchor='nw', width=360)
        left_canvas.pack(side='left', fill='both', expand=True)
        left_scroll.pack(side='right', fill='y')
        self._bind_mousewheel_recursive(left_canvas, left_inner)

        self._build_settings(left_inner)

        # 右侧辩论实况
        right_panel = tk.Frame(content, bg=colors["bg_panel"])
        right_panel.pack(side='left', fill='both', expand=True)
        self._build_chat_area(right_panel)

    def _bind_mousewheel_recursive(self, canvas: tk.Canvas, widget: tk.Widget) -> None:
        """递归绑定鼠标滚轮事件到 canvas。"""
        widget.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(canvas, child)

    # =====================================================================
    # 设置面板构建
    # =====================================================================

    def _build_settings(self, parent: tk.Frame) -> None:
        """构建设置面板中的所有控件。"""
        colors = self.theme_colors
        p = parent  # 简写

        tk.Label(p, text="⚙️ 辩论设置", font=('微软雅黑', 14, 'bold'),
                 fg=colors["fg_label"], bg=colors["bg_panel"]).pack(padx=20, pady=(15, 10), anchor='w')
        self._add_separator(p)

        # --- 辩题选择 ---
        self._section_label(p, "📋 辩题")
        topic_frame = tk.Frame(p, bg=colors["bg_panel"])
        topic_frame.pack(fill='x', padx=20, pady=(0, 5))
        self.topic_entry = tk.Entry(topic_frame, font=('微软雅黑', 11),
                                    bg=colors["bg_entry"], fg=colors["fg_entry"],
                                    insertbackground=colors["fg_entry"], relief='flat', bd=0)
        self.topic_entry.pack(side='left', fill='x', expand=True, ipady=8)
        self.topic_entry.insert(0, PRESET_TOPICS[0])
        self.topic_var = tk.StringVar(value=PRESET_TOPICS[0])
        topic_combo = ttk.Combobox(topic_frame, textvariable=self.topic_var, values=PRESET_TOPICS,
                                   state="readonly", width=20)
        topic_combo.pack(side='left', padx=(5, 0))
        topic_combo.bind("<<ComboboxSelected>>", self._on_topic_selected)
        self._add_separator(p)

        # --- API 密钥 ---
        self._section_label(p, "🔑 API 密钥 (必填)")
        self.api_key_entry = tk.Entry(p, font=('微软雅黑', 10), show='*',
                                      bg=colors["bg_entry"], fg=colors["fg_entry"],
                                      insertbackground=colors["fg_entry"], relief='flat', bd=0)
        self.api_key_entry.pack(fill='x', padx=20, ipady=8, pady=(5, 5))
        self._add_separator(p)

        # --- 环节卡片 ---
        self._section_label(p, "🔄 辩论环节（每环节独立调节）")
        for stage_def in STAGE_DEFS:
            self._create_stage_card(p,
                                    f'{stage_def["icon"]} {stage_def["name"]}',
                                    f'{stage_def["pro_speaker"]} vs {stage_def["con_speaker"]}',
                                    f'{stage_def["pro_duty"][:20]}…',
                                    default_val="1", var_name=stage_def["key"])
        self._add_separator(p)

        # --- 高级选项 ---
        self._section_label(p, "⚡ 高级选项")

        self.pro_first_var = tk.BooleanVar(value=True)
        tk.Checkbutton(p, text="正方先发言", variable=self.pro_first_var,
                       font=('微软雅黑', 10), fg=colors["fg_sec"], bg=colors["bg_panel"],
                       selectcolor=colors["highlight"], activebackground=colors["bg_panel"],
                       activeforeground=colors["fg_label"]).pack(padx=20, anchor='w')

        # 字数限制
        word_frame = tk.Frame(p, bg=colors["bg_panel"]); word_frame.pack(fill='x', padx=20, pady=(8,0))
        tk.Label(word_frame, text="每轮字数上限：", font=('微软雅黑',10), fg=colors["fg_sec"], bg=colors["bg_panel"]).pack(side='left')
        self.word_var = tk.StringVar(value="300")
        tk.Spinbox(word_frame, from_=10, to=2000, increment=50, textvariable=self.word_var, width=6,
                   font=('微软雅黑',10), bg=colors["bg_entry"], fg=colors["fg_entry"],
                   buttonbackground=colors["highlight"], relief='flat', bd=0, justify='center').pack(side='left', padx=(5,0))
        tk.Label(word_frame, text="字", font=('微软雅黑',9), fg=colors["fg_sec"], bg=colors["bg_panel"]).pack(side='left', padx=(3,0))

        # Token 截断
        token_frame = tk.Frame(p, bg=colors["bg_panel"]); token_frame.pack(fill='x', padx=20, pady=(8,0))
        tk.Label(token_frame, text="单轮 Token 上限：", font=('微软雅黑',10), fg=colors["fg_sec"], bg=colors["bg_panel"]).pack(side='left')
        self.token_var = tk.StringVar(value="0")
        tk.Spinbox(token_frame, from_=0, to=5000, increment=100, textvariable=self.token_var, width=6,
                   font=('微软雅黑',10), bg=colors["bg_entry"], fg=colors["fg_entry"],
                   buttonbackground=colors["highlight"], relief='flat', bd=0, justify='center').pack(side='left', padx=(5,0))
        tk.Label(token_frame, text="(0=不限)", font=('微软雅黑',9), fg=colors["fg_sec"], bg=colors["bg_panel"]).pack(side='left', padx=(3,0))

        # 字体大小
        font_frm = tk.Frame(p, bg=colors["bg_panel"]); font_frm.pack(fill='x', padx=20, pady=(8,0))
        tk.Label(font_frm, text="显示字号：", font=('微软雅黑',10), fg=colors["fg_sec"], bg=colors["bg_panel"]).pack(side='left')
        self.font_size_var = tk.StringVar(value=str(self.font_size))
        tk.Spinbox(font_frm, from_=8, to=24, increment=1, textvariable=self.font_size_var, width=4,
                   font=('微软雅黑',10), bg=colors["bg_entry"], fg=colors["fg_entry"],
                   buttonbackground=colors["highlight"], relief='flat', bd=0, justify='center',
                   command=self._on_font_change).pack(side='left', padx=(5,0))
        tk.Label(font_frm, text="pt", font=('微软雅黑',9), fg=colors["fg_sec"], bg=colors["bg_panel"]).pack(side='left')

        # 主题切换
        theme_frm = tk.Frame(p, bg=colors["bg_panel"]); theme_frm.pack(fill='x', padx=20, pady=(10,0))
        tk.Label(theme_frm, text="界面主题：", font=('微软雅黑',10), fg=colors["fg_sec"], bg=colors["bg_panel"]).pack(side='left')
        self.theme_var = tk.StringVar(value=self.current_theme)
        theme_combo = ttk.Combobox(theme_frm, textvariable=self.theme_var, values=["暗色","亮色"], state="readonly", width=8)
        theme_combo.pack(side='left', padx=(5,0))
        theme_combo.bind("<<ComboboxSelected>>", lambda e: self.toggle_theme(self.theme_var.get()))

        # 统计与状态
        self.stats_label = tk.Label(p, text="", font=('微软雅黑',9), fg=colors["fg_sec"], bg=colors["bg_panel"], justify='left')
        self.stats_label.pack(padx=20, anchor='w', pady=(12,0))
        self._update_stats()

        # 控制按钮
        btn_frm = tk.Frame(p, bg=colors["bg_panel"]); btn_frm.pack(fill='x', padx=20, pady=(10,5))
        self.start_btn = tk.Button(btn_frm, text="▶ 开始辩论", font=('微软雅黑',12,'bold'),
                                    bg=colors["btn_bg"], fg=colors["btn_fg"], relief='flat', cursor='hand2',
                                    padx=10, pady=8, command=self.start_debate)
        self.start_btn.pack(side='left', fill='x', expand=True, padx=(0,2))
        self.pause_btn = tk.Button(btn_frm, text="⏸ 暂停", font=('微软雅黑',11),
                                    bg=colors["btn_secondary_bg"], fg=colors["btn_secondary_fg"],
                                    relief='flat', cursor='hand2', padx=10, pady=8, command=self.toggle_pause, state='disabled')
        self.pause_btn.pack(side='left', padx=2)
        self.stop_btn = tk.Button(btn_frm, text="⏹ 终止", font=('微软雅黑',11),
                                   bg=colors["btn_secondary_bg"], fg=colors["btn_secondary_fg"],
                                   relief='flat', cursor='hand2', padx=10, pady=8, command=self.stop_debate, state='disabled')
        self.stop_btn.pack(side='left', padx=(2,0))

        # 导入导出
        io_frm = tk.Frame(p, bg=colors["bg_panel"]); io_frm.pack(fill='x', padx=20, pady=(8,0))
        self.export_btn = tk.Button(io_frm, text="📤 导出记录", font=('微软雅黑',10), bg=colors["btn_secondary_bg"],
                                     fg=colors["btn_secondary_fg"], relief='flat', cursor='hand2', padx=8, pady=4,
                                     command=self.export_record)
        self.export_btn.pack(side='left', padx=(0,5))
        self.import_btn = tk.Button(io_frm, text="📥 导入记录", font=('微软雅黑',10), bg=colors["btn_secondary_bg"],
                                     fg=colors["btn_secondary_fg"], relief='flat', cursor='hand2', padx=8, pady=4,
                                     command=self.import_record)
        self.import_btn.pack(side='left')

        # 进度条
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("custom.Horizontal.TProgressbar", background=colors["btn_bg"], troughcolor=colors["progress_trough"])
        self.progress_bar = ttk.Progressbar(p, style="custom.Horizontal.TProgressbar", mode='determinate')
        self.progress_bar.pack(fill='x', padx=20, pady=(10,2))
        self.progress_label = tk.Label(p, text="发言进度：0/0", font=('微软雅黑',9), fg=colors["fg_sec"], bg=colors["bg_panel"])
        self.progress_label.pack(padx=20, anchor='w')
        self.time_label = tk.Label(p, text="", font=('微软雅黑',9), fg=colors["fg_sec"], bg=colors["bg_panel"])
        self.time_label.pack(padx=20, anchor='w', pady=(0,5))
        self.status_label = tk.Label(p, text="● 准备就绪", font=('微软雅黑',9), fg=colors["fg_sec"], bg=colors["bg_panel"])
        self.status_label.pack(pady=(0,15))

    def _on_topic_selected(self, event: Any = None) -> None:
        """辩题下拉选择事件。"""
        self.topic_entry.delete(0, 'end')
        self.topic_entry.insert(0, self.topic_var.get())

    def _create_stage_card(self, parent: tk.Frame, title: str, speakers: str,
                           desc: str, default_val: str, var_name: str) -> tk.Frame:
        """创建环节配置卡片。"""
        colors = self.theme_colors
        card = tk.Frame(parent, bg=colors["bg_card"], bd=0,
                        highlightthickness=1, highlightbackground=colors["separator"])
        card.pack(fill='x', padx=20, pady=5)
        header = tk.Frame(card, bg=colors["bg_panel"]); header.pack(fill='x')
        tk.Label(header, text=title, font=('微软雅黑',11,'bold'),
                 fg=colors["fg_label"], bg=colors["bg_panel"]).pack(side='left', padx=12, pady=(8,2))
        tk.Label(card, text=speakers, font=('微软雅黑',9), fg=colors["fg_sec"], bg=colors["bg_card"]).pack(padx=12, anchor='w')
        tk.Label(card, text=desc, font=('微软雅黑',8), fg=colors["fg_sec"], bg=colors["bg_card"]).pack(padx=12, anchor='w', pady=(2,5))
        ctrl = tk.Frame(card, bg=colors["bg_card"]); ctrl.pack(fill='x', padx=12, pady=(0,10))
        tk.Label(ctrl, text="每方发言轮数：", font=('微软雅黑',9), fg=colors["fg_sec"], bg=colors["bg_card"]).pack(side='left')
        spinbox = tk.Spinbox(ctrl, from_=0, to=100, increment=1, width=5,
                             font=('微软雅黑',11), bg=colors["bg_entry"], fg=colors["fg_entry"],
                             buttonbackground=colors["highlight"], relief='flat', bd=0,
                             justify='center', readonlybackground=colors["highlight"],
                             command=self._update_stats)
        spinbox.delete(0, 'end')
        spinbox.insert(0, default_val)
        spinbox.pack(side='left', padx=(8,0))
        spinbox.bind('<<Increment>>', lambda e: self._update_stats())
        spinbox.bind('<<Decrement>>', lambda e: self._update_stats())
        spinbox.bind('<KeyRelease>', lambda e: self._update_stats())
        self.stage_spinboxes[var_name] = spinbox
        return card

    def _section_label(self, parent: tk.Frame, text: str) -> None:
        """插入带强调色的小节标题。"""
        tk.Label(parent, text=text, font=('微软雅黑',11,'bold'),
                 fg='#f59e0b', bg=parent.cget("bg")).pack(padx=20, anchor='w', pady=(10,5))

    def _add_separator(self, parent: tk.Frame) -> None:
        """分割线。"""
        tk.Frame(parent, bg=self.theme_colors["separator"], height=1).pack(fill='x', padx=20, pady=(6,6))

    def _build_chat_area(self, parent: tk.Frame) -> None:
        """右侧辩论实况文本区域。"""
        colors = self.theme_colors
        tk.Label(parent, text="📜 辩论实况", font=('微软雅黑', 14, 'bold'),
                 fg=colors["fg_label"], bg=colors["bg_panel"]).pack(padx=20, pady=(15,10), anchor='w')
        self.chat_area = scrolledtext.ScrolledText(
            parent, font=('微软雅黑', self.font_size), bg=colors["bg_entry"],
            fg=colors["fg_entry"], relief='flat', wrap='word', state='disabled',
            borderwidth=0, padx=20, pady=15,
        )
        self.chat_area.pack(fill='both', expand=True, padx=10, pady=(0,10))
        for tag, cfg in TEXT_TAG_CONFIGS.items():
            self.chat_area.tag_config(tag, **cfg)

    # =====================================================================
    # 统计与进度
    # =====================================================================

    def _update_stats(self, *args) -> None:
        """重新计算总发言数，更新统计标签与按钮状态。"""
        counts = []
        for i in range(1,5):
            key = f'stage{i}'
            if key in self.stage_spinboxes:
                try:
                    counts.append(int(self.stage_spinboxes[key].get()))
                except ValueError:
                    counts.append(0)
        self.total_speeches = sum(counts) * 2
        self.stats_label.config(
            text=f"📊 总轮数: {sum(counts)} | 总发言: {self.total_speeches} 条\n"
                 f"   一辩:{counts[0]} | 二辩:{counts[1]} | 三辩:{counts[2]} | 四辩:{counts[3]}"
        )
        if hasattr(self, 'start_btn'):
            if sum(counts) == 0:
                self.start_btn.config(state='disabled', text='至少设置1轮', bg=self.theme_colors["btn_disabled_bg"])
            else:
                self.start_btn.config(state='normal', text='▶ 开始辩论')

    def _update_progress(self, completed: int) -> None:
        """更新进度条和预估时间。"""
        self.completed_speeches = completed
        total = self.total_speeches
        if total > 0:
            self.progress_bar['maximum'] = total
            self.progress_bar['value'] = min(completed, total)
            self.progress_label.config(text=f"发言进度：{completed}/{total}")
        if self.start_time and completed > 0:
            elapsed = time.time() - self.start_time
            avg = elapsed / completed
            remaining = (total - completed) * avg
            self.time_label.config(text=f"已用时：{elapsed:.0f}秒 | 预估剩余：{remaining:.0f}秒")
        else:
            self.time_label.config(text="")

    # =====================================================================
    # 辩论控制
    # =====================================================================

    def start_debate(self) -> None:
        """验证输入，创建引擎并启动辩论。"""
        if self.is_running:
            return
        api_key = self.api_key_entry.get().strip()
        if not api_key:
            self.append_text('\n❌ 请填写 API 密钥！\n', 'con_text')
            return
        if len(api_key) < 5 or not re.match(r'^[A-Za-z0-9\-_]+$', api_key):
            self.append_text('\n⚠️ API 密钥格式可能不正确\n', 'info')

        topic = self.topic_entry.get().strip()
        if not topic:
            self.append_text('\n❌ 辩题不能为空\n', 'con_text')
            return

        try:
            word_limit = int(self.word_var.get())
            if word_limit < 10:
                word_limit = 10
                self.word_var.set("10")
        except ValueError:
            word_limit = 300
        try:
            max_tokens = int(self.token_var.get())
        except ValueError:
            max_tokens = 0

        stages = {}
        for i in range(1,5):
            key = f'stage{i}'
            spinbox = self.stage_spinboxes.get(key)
            try:
                val = int(spinbox.get()) if spinbox else 0
                stages[key] = max(0, min(val, 100))
            except ValueError:
                stages[key] = 0
        if all(v == 0 for v in stages.values()):
            self.append_text('\n⚠️ 至少需要设置一个环节轮数\n', 'con_text')
            return

        config = DebateConfig(
            topic=topic,
            stages=stages,
            word_limit=word_limit,
            pro_first=self.pro_first_var.get(),
            api_key=api_key,
            max_tokens=max_tokens,
        )

        # 重置 UI
        self._clear_chat()
        self.history.clear()
        self.completed_speeches = 0
        self.start_time = time.time()
        self._update_progress(0)
        self.set_status('● 准备开始...', '#f59e0b')

        # 创建引擎，传入回调
        self.engine = DebateEngine(config, event_callback=self._enqueue_event)
        self.engine.start()
        self.is_running = True
        self.is_paused = False
        self.start_btn.config(state='disabled', text='⏳ 辩论中...')
        self.pause_btn.config(state='normal', text='⏸ 暂停')
        self.stop_btn.config(state='normal', text='⏹ 终止')
        self.root.after(UI_REFRESH_MS, self._process_queue)

    def toggle_pause(self) -> None:
        """切换暂停/继续。"""
        if not self.is_running or self.engine is None:
            return
        if self.is_paused:
            self.engine.resume()
            self.is_paused = False
            self.pause_btn.config(text='⏸ 暂停')
            self.set_status('● 辩论进行中', '#f59e0b')
        else:
            self.engine.pause()
            self.is_paused = True
            self.pause_btn.config(text='▶ 继续')
            self.set_status('⏸ 辩论已暂停', '#f59e0b')

    def stop_debate(self) -> None:
        """终止辩论。"""
        if not self.is_running:
            return
        self._stop_engine()
        self.is_running = False
        self.is_paused = False
        self.pause_btn.config(state='disabled', text='⏸ 暂停')
        self.stop_btn.config(state='disabled', text='⏹ 终止')
        self.start_btn.config(state='normal', text='▶ 开始辩论')
        self.set_status('● 辩论已终止', '#ef4444')
        self.append_text('\n⚠️ 辩论已被用户终止\n', 'info')
        self._update_stats()

    # =====================================================================
    # 事件回调与队列处理（线程安全）
    # =====================================================================

    def _enqueue_event(self, event: Dict[str, Any]) -> None:
        """引擎回调：将事件放入线程安全队列。"""
        self.event_queue.put(event)

    def _process_queue(self) -> None:
        """定时轮询队列，将事件应用到 UI。"""
        batch = []
        for _ in range(20):
            try:
                batch.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        for msg in batch:
            self._display_event(msg, live_mode=self.is_running)

        if self.is_running and not self._closing:
            self.root.after(UI_REFRESH_MS, self._process_queue)
        else:
            # 结束前清空剩余事件
            try:
                while True:
                    msg = self.event_queue.get_nowait()
                    self._display_event(msg, live_mode=False)
            except queue.Empty:
                pass
            if self.start_time:
                elapsed = time.time() - self.start_time
                self.time_label.config(text=f"总用时：{elapsed:.0f}秒")
            self._update_stats()

    def _display_event(self, msg: Dict[str, Any], live_mode: bool = True) -> None:
        """根据事件类型更新历史与界面。

        Args:
            msg: 事件字典。
            live_mode: 若为实时辩论，会更新进度和状态。
        """
        self.history.append(msg)
        if len(self.history) > MAX_HISTORY_ITEMS:
            self.history = self.history[-MAX_HISTORY_ITEMS:]

        msg_type = msg['type']
        if msg_type == 'topic':
            self.append_text('\n', 'divider')
            self.append_text('📋 辩题\n', 'topic_label')
            self.append_text(f'{msg["content"]}\n', 'topic')
            self.append_text('┈' * 70 + '\n', 'divider')
            s = msg.get('stages', {})
            self.append_text(
                f'一辩:{s.get("stage1",0)}轮 | 二辩:{s.get("stage2",0)}轮 | '
                f'三辩:{s.get("stage3",0)}轮 | 四辩:{s.get("stage4",0)}轮\n', 'info')
            self.append_text('┈' * 70 + '\n\n', 'divider')
        elif msg_type == 'stage':
            icon = next((d['icon'] for d in STAGE_DEFS if d['key'] == msg.get('stage_key')), '▶')
            self.append_text(f'\n{"━" * 70}\n', 'divider')
            self.append_text(f'  {icon} {msg["stage_name"]}\n', 'stage_header')
            self.append_text(f'{"━" * 70}\n\n', 'divider')
            if live_mode:
                self.set_status(f'⏳ {msg["stage_name"]}...', '#a78bfa')
        elif msg_type == 'message':
            r = msg.get('round', 0)
            t = msg.get('total_rounds', 0)
            if msg['role'] == 'ProSpeaker':
                self.append_text(f'🔵 {msg["speaker_name"]} (第{r}/{t}轮)\n', 'pro_label')
                self.append_text(f'{msg["content"]}\n\n', 'pro_text')
            else:
                self.append_text(f'🔴 {msg["speaker_name"]} (第{r}/{t}轮)\n', 'con_label')
                self.append_text(f'{msg["content"]}\n\n', 'con_text')
            if live_mode:
                self._update_progress(self.completed_speeches + 1)
        elif msg_type == 'end':
            self.append_text('\n' + '★' * 70 + '\n', 'divider')
            self.append_text('🏆 辩论结束\n', 'end')
            self.append_text(generate_debate_summary(self.history) + '\n', 'info')
            self.append_text('★' * 70 + '\n', 'divider')
            if live_mode:
                self.set_status('● 辩论结束 ✓', '#22c55e')
                self.is_running = False
                self._stop_engine()
        elif msg_type == 'error':
            self.append_text(f'\n❌ 错误：{msg["content"]}\n', 'con_text')
            if live_mode:
                self.set_status('● 出错', '#ef4444')
                self.is_running = False
                self._stop_engine()
        elif msg_type == 'warning':
            self.append_text(f'\n⚠️ {msg["content"]}\n', 'info')

    # =====================================================================
    # 文本插入与聊天区管理
    # =====================================================================

    def append_text(self, text: str, tag: Optional[str] = None) -> None:
        """主线程安全地追加文本到聊天区并限制行数。"""
        if self._closing or not self.root.winfo_exists():
            return
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, lambda: self.append_text(text, tag))
            return
        try:
            self.chat_area.configure(state='normal')
            self.chat_area.insert('end', text, tag)
            self._limit_chat_lines()
            self.chat_area.see('end')
            self.chat_area.configure(state='disabled')
        except tk.TclError:
            pass

    def _limit_chat_lines(self) -> None:
        """若行数超过上限，删除前部旧内容。"""
        try:
            end_idx = self.chat_area.index('end-1c')
            line_count = int(end_idx.split('.')[0])
            if line_count > MAX_CHAT_LINES:
                self.chat_area.delete('1.0', f"{CHAT_TRIM_LINES}.0")
        except Exception:
            pass

    def _clear_chat(self) -> None:
        """清空聊天区。"""
        self.chat_area.configure(state='normal')
        self.chat_area.delete('1.0', 'end')
        self.chat_area.configure(state='disabled')

    def set_status(self, text: str, color: str = '#64748b') -> None:
        """更新状态栏文字（线程安全）。"""
        if self._closing or not self.root.winfo_exists():
            return
        def _set():
            try:
                self.status_label.config(text=text, fg=color)
            except tk.TclError:
                pass
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, _set)
        else:
            _set()

    # =====================================================================
    # 导入导出
    # =====================================================================

    def export_record(self) -> None:
        """导出辩论历史为 Markdown 或 JSON。"""
        if not self.history:
            messagebox.showinfo("提示", "暂无辩论记录可导出")
            return
        topic = self.topic_entry.get().strip() or "未知辩题"
        file_path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown 文件", "*.md"), ("JSON 文件", "*.json")],
            title="导出辩论记录",
            initialfile=f"辩论记录_{topic[:10]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        )
        if not file_path:
            return
        try:
            if file_path.lower().endswith('.json'):
                content = export_to_json(self.history, topic)
            else:
                content = export_to_markdown(self.history, topic)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            messagebox.showinfo("导出成功", f"辩论记录已保存至：\n{file_path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
            logger.exception("导出记录失败")

    def import_record(self) -> None:
        """从文件导入辩论记录（覆盖当前）。"""
        file_path = filedialog.askopenfilename(
            title="导入辩论记录",
            filetypes=[("Markdown/JSON 文件", "*.md *.json"), ("所有文件", "*.*")]
        )
        if not file_path:
            return
        if self.history and not messagebox.askyesno("覆盖确认", "当前已有辩论记录，导入将覆盖现有内容，是否继续？"):
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            messagebox.showerror("读取失败", f"无法读取文件：{e}")
            return

        self._clear_chat()
        if file_path.lower().endswith('.json'):
            try:
                data = json.loads(content)
            except json.JSONDecodeError as e:
                messagebox.showerror("格式错误", f"JSON 解析失败：{e}")
                return
            if not isinstance(data, dict) or "messages" not in data:
                messagebox.showerror("格式错误", "JSON 缺少 'messages' 字段")
                return
            self.history.clear()
            for msg in data["messages"]:
                if isinstance(msg, dict) and "type" in msg:
                    self.history.append(msg)
                    self._display_event(msg, live_mode=False)
            if "summary" in data:
                self.append_text('\n' + data["summary"] + '\n', 'info')
            messagebox.showinfo("导入成功", "辩论记录已加载（仅查看模式）")
        else:
            # Markdown 直接显示
            self.chat_area.configure(state='normal')
            self.chat_area.insert('end', content)
            self.chat_area.configure(state='disabled')
            self.history.clear()
            messagebox.showinfo("导入成功", "Markdown 记录已显示（仅查看模式）")

    def _on_font_change(self) -> None:
        """字体大小变更回调。"""
        try:
            new = int(self.font_size_var.get())
            if 8 <= new <= 24:
                self.font_size = new
                self.chat_area.configure(font=('微软雅黑', new))
        except ValueError:
            pass