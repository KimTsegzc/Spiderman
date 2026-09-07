"""SpiderMan V2.3.

Windows desktop automation tool with task editing, loop execution,
JSON save/load, and simple mouse/keyboard/wait actions.
"""

from __future__ import annotations

import json
import base64
import io
import queue
import threading
import time
import ctypes
import csv
import re
import sys
import tempfile
from ctypes import wintypes
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk, filedialog

from avatar_embedded import AVATAR_PNG_BASE64
from logo_embedded import SPIDERMAN_JFIF_BASE64, SPIDERMAN_ICO_BASE64

_pyautogui = None
_pyperclip = None


def _get_runtime_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = _get_runtime_app_dir()
TASK_DIR = APP_DIR / "tasks"
TASK_DIR.mkdir(exist_ok=True)
APP_NAME = "蜘蛛侠"
APP_VERSION = "V2.3"
APP_AUTHOR = "广州分行 xiexin1.gd"
APP_USER_MODEL_ID = "ccb.spiderman.app.v2_3"
GLOBAL_START_HOTKEY_LABEL = "Ctrl+F5"
GLOBAL_STOP_HOTKEY_LABEL = "Ctrl+Shift+Alt+W"
GLOBAL_RECORD_STOP_HOTKEY_LABEL = "Ctrl+Shift+Alt+R"
HOTKEY_ID_START = 0xB000
HOTKEY_ID_STOP = 0xB001
HOTKEY_ID_RECORD_STOP = 0xB002
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

BUILTIN_TASKS: Dict[str, Dict[str, Any]] = {
    "auto_test": {
        "version": 1,
        "name": "auto_test",
        "loop_count": 1,
        "delay_seconds": 0.3,
        "steps": [
            {"type": "key", "combo": "win"},
            {"type": "paste", "items": ["chrome"]},
            {"type": "key", "combo": "enter"},
            {"type": "wait", "seconds": 1.0},
            {"type": "key", "combo": "ctrl+l"},
            {"type": "paste", "items": ["www.ccb.com"]},
            {"type": "key", "combo": "enter"},
        ],
    },
    "auto_testloop": {
        "version": 1,
        "name": "auto_testloop",
        "loop_count": 1,
        "delay_seconds": 0.3,
        "steps": [
            {"type": "key", "combo": "win"},
            {"type": "paste", "items": ["chrome"]},
            {"type": "key", "combo": "enter"},
            {"type": "wait", "seconds": 1.0},
            {"type": "loop", "loop_count": 5},
            {"type": "key", "combo": "ctrl+t"},
            {"type": "key", "combo": "ctrl+l"},
            {"type": "paste-csv", "input_expr": "input.C", "columns": ["C"]},
            {"type": "key", "combo": "enter"},
            {"type": "section", "title": "退出循环", "note": ""},
            {"type": "key", "combo": "alt+F4"},
        ],
    },
}

BUILTIN_LIST_PREFIX = "[内置] "


def _enable_high_dpi_awareness() -> None:
    """Enable DPI awareness before creating Tk root to avoid blurry first render."""
    try:
        user32 = ctypes.windll.user32
        # -4 is DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
    except Exception:
        pass
    try:
        shcore = ctypes.windll.shcore
        # 2 means PROCESS_PER_MONITOR_DPI_AWARE.
        shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _set_windows_app_user_model_id() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


class StepEditor:
    @staticmethod
    def parse_paste_items_text(raw: str) -> List[str]:
        text = raw.strip()
        if not text:
            return []

        # Backward compatibility: accept historical JSON array format.
        if text.startswith("[") and text.endswith("]"):
            try:
                data = json.loads(text)
                if isinstance(data, list) and all(isinstance(item, str) for item in data):
                    return [item.strip() for item in data if item.strip()]
            except Exception:
                pass

        normalized = text.replace("，", ",")
        return [part.strip() for part in normalized.split(",") if part.strip()]

    def __init__(
        self,
        master: tk.Widget,
        index: int,
        on_delete,
        on_move_up,
        on_move_down,
        on_duplicate,
        on_select=None,
        on_mousewheel=None,
        on_paste_changed=None,
        get_next_section_name=None,
    ):
        self.master = master
        self.index = index
        self.on_delete = on_delete
        self.on_move_up = on_move_up
        self.on_move_down = on_move_down
        self.on_duplicate = on_duplicate
        self.on_select = on_select
        self.on_mousewheel = on_mousewheel
        self.on_paste_changed = on_paste_changed
        self.get_next_section_name = get_next_section_name
        self._section_name_cache: str | None = None
        self.is_selected = False
        self.in_subloop_body = False
        self.frame = ttk.Frame(master, padding=(6, 7), style="StepCard.TFrame")
        self.frame.columnconfigure(0, weight=1)

        self.header = ttk.Frame(self.frame, style="StepCard.TFrame")
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.columnconfigure(2, weight=1)
        self.title_var = tk.StringVar(value=f"步骤 {index + 1}")
        self.title_label = ttk.Label(self.header, textvariable=self.title_var)
        self.title_label.grid(row=0, column=0, sticky="w")
        self.type_var = tk.StringVar(value="click")
        self.type_box = ttk.Combobox(
            self.header,
            textvariable=self.type_var,
            values=["click", "paste", "paste-csv", "key", "wait", "section", "loop"],
            state="readonly",
            width=8,
            style="StepType.TCombobox",
        )
        self.type_box.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.type_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_fields())

        self.buttons = ttk.Frame(self.header, style="StepCard.TFrame")
        self.buttons.grid(row=0, column=3, sticky="e")
        ttk.Button(self.buttons, text="+", width=2, style="StepRound.TButton", command=self.on_duplicate).grid(row=0, column=0, padx=1)
        ttk.Button(self.buttons, text="↑", width=2, style="StepRound.TButton", command=self.on_move_up).grid(row=0, column=1, padx=1)
        ttk.Button(self.buttons, text="↓", width=2, style="StepRound.TButton", command=self.on_move_down).grid(row=0, column=2, padx=1)
        ttk.Button(self.buttons, text="×", width=2, style="StepRound.TButton", command=self.on_delete).grid(row=0, column=3, padx=1)

        self.body = ttk.Frame(self.frame, style="StepCard.TFrame")
        self.body.grid(row=1, column=0, sticky="ew", pady=(10, 2))
        self.body.columnconfigure(1, weight=1)

        self.fields: Dict[str, Any] = {}
        self.refresh_fields()
        self._bind_select_handlers()

    def refresh_index(self, index: int, loop_body_step_no: int = 0) -> None:
        self.index = index
        current = self.type_var.get()
        if current == "section":
            self.title_var.set(self._section_name_cache or f"阶段 {index + 1}")
        elif current in ("loop", "subloop"):
            self.title_var.set("进入循环")
        elif loop_body_step_no > 0:
            self.title_var.set(f"步骤sub{loop_body_step_no}")
        else:
            self.title_var.set(f"步骤 {index + 1}")

    def clear_body(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self.fields = {}

    def reset_to_default(self) -> None:
        self.type_var.set("click")
        self.refresh_fields()

    def clear_values(self) -> None:
        current = self.type_var.get()
        if current == "click":
            self.fields["x"].set("0")
            self.fields["y"].set("0")
            self.fields["button"].set("left")
        elif current == "paste":
            self.fields["items"].set("文本1, 文本2")
        elif current == "paste-csv":
            self.fields["input_expr"].set("input.A")
        elif current == "key":
            self.fields["combo"].set("tab")
        elif current == "wait":
            self.fields["seconds"].set("1")
        elif current == "section":
            self.fields["title"].set(self._section_name_cache or "阶段")
            self.fields["note"].set("")
        elif current in ("loop", "subloop"):
            self.fields["loop_count"].set("2")

    def refresh_fields(self) -> None:
        current = self.type_var.get()
        self.clear_body()
        if current == "click":
            self._build_click_fields()
        elif current == "paste":
            self._build_paste_fields()
        elif current == "paste-csv":
            self._build_paste_csv_fields()
        elif current == "key":
            self._build_key_fields()
        elif current == "section":
            self._build_section_fields()
        elif current in ("loop", "subloop"):
            self._build_subloop_fields()
        else:
            self._build_wait_fields()
        self._refresh_title_style()
        self._apply_card_style()
        self._bind_select_handlers()
        if self.on_paste_changed:
            self.on_paste_changed()

    def _refresh_title_style(self) -> None:
        current = self.type_var.get()
        if self.is_selected:
            suffix = "Selected"
        elif self.in_subloop_body:
            suffix = "Subloop"
        else:
            suffix = ""
        if current == "section":
            style_name = f"SectionStepTitle{suffix}.TLabel"
        elif current in ("loop", "subloop"):
            style_name = f"SubloopStepTitle{suffix}.TLabel"
        else:
            style_name = f"StepTitle{suffix}.TLabel"
        self.title_label.configure(style=style_name)

    def _apply_card_style(self) -> None:
        if self.is_selected:
            style = "StepCardSelected.TFrame"
        elif self.in_subloop_body:
            style = "StepCardSubloop.TFrame"
        else:
            style = "StepCard.TFrame"
        # Keep identical geometry across states to avoid visual "jump" on focus switch.
        self.frame.configure(padding=(6, 7))
        self.frame.configure(style=style)
        self.header.configure(style=style)
        self.buttons.configure(style=style)
        self.body.configure(style=style)
        if self.is_selected:
            label_style = "StepCardSelectedText.TLabel"
        elif self.in_subloop_body:
            label_style = "StepCardSubloopText.TLabel"
        else:
            label_style = "StepCardText.TLabel"
        self._apply_body_label_style(self.frame, label_style)
        self._refresh_title_style()

    def _apply_body_label_style(self, widget: tk.Widget, label_style: str) -> None:
        for child in widget.winfo_children():
            if isinstance(child, ttk.Label) and child is not self.title_label:
                child.configure(style=label_style)
            self._apply_body_label_style(child, label_style)

    def set_selected(self, selected: bool) -> None:
        self.is_selected = selected
        self._apply_card_style()

    def set_in_subloop_body(self, in_subloop_body: bool) -> None:
        self.in_subloop_body = in_subloop_body
        self._apply_card_style()

    def _bind_select_handlers(self) -> None:
        def _bind_widget(widget: tk.Widget) -> None:
            widget.bind("<Button-1>", self._on_widget_selected, add="+")
            widget.bind("<MouseWheel>", self._on_widget_mousewheel, add="+")
            if isinstance(widget, (ttk.Entry, ttk.Combobox, tk.Entry, tk.Text)):
                widget.bind("<FocusIn>", self._on_widget_selected, add="+")
            for child in widget.winfo_children():
                _bind_widget(child)

        _bind_widget(self.frame)

    def _on_widget_selected(self, event=None) -> None:
        if callable(self.on_select):
            focus_widget = event.widget if event is not None and hasattr(event, "widget") else None
            self.on_select(self, focus_widget)

    def _on_widget_mousewheel(self, event=None):
        if callable(self.on_mousewheel):
            return self.on_mousewheel(event)
        return None

    def clear_input_selection(self) -> None:
        def _walk(widget: tk.Widget) -> None:
            for child in widget.winfo_children():
                try:
                    if isinstance(child, ttk.Combobox):
                        # Keep readonly combobox value intact; only drop focus visuals.
                        child.icursor(tk.END)
                    elif isinstance(child, (ttk.Entry, tk.Entry)):
                        child.selection_clear()
                        child.icursor(tk.END)
                except Exception:
                    pass
                _walk(child)

        _walk(self.frame)

    def _build_click_fields(self) -> None:
        ttk.Label(self.body, text="X").grid(row=0, column=0, sticky="w")
        x_var = tk.StringVar(value="0")
        ttk.Entry(self.body, textvariable=x_var, width=8).grid(row=0, column=1, sticky="w", padx=(4, 8))
        ttk.Label(self.body, text="Y").grid(row=0, column=2, sticky="w")
        y_var = tk.StringVar(value="0")
        ttk.Entry(self.body, textvariable=y_var, width=8).grid(row=0, column=3, sticky="w", padx=(4, 8))
        ttk.Label(self.body, text="按钮").grid(row=0, column=4, sticky="w")
        btn_var = tk.StringVar(value="left")
        ttk.Combobox(
            self.body,
            textvariable=btn_var,
            values=["left", "right"],
            state="readonly",
            width=7,
        ).grid(
            row=0, column=5, sticky="w", padx=(4, 0)
        )
        ttk.Label(self.body, text="点击").grid(row=0, column=6, sticky="w", padx=(8, 0))
        clicks_var = tk.StringVar(value="single")
        ttk.Combobox(
            self.body,
            textvariable=clicks_var,
            values=["single", "double", "triple"],
            state="readonly",
            width=8,
        ).grid(row=0, column=7, sticky="w", padx=(4, 0))
        self.fields = {"x": x_var, "y": y_var, "button": btn_var, "click_mode": clicks_var}

    def _build_paste_fields(self) -> None:
        ttk.Label(self.body, text="文本数组(逗号分隔)").grid(row=0, column=0, sticky="w")
        items_var = tk.StringVar(value="文本1, 文本2")
        entry = ttk.Entry(self.body, textvariable=items_var)
        entry.grid(row=0, column=1, columnspan=5, sticky="ew", padx=(6, 0))
        if self.on_paste_changed:
            items_var.trace_add("write", lambda *_args: self.on_paste_changed())
            entry.bind("<FocusOut>", lambda _event: self.on_paste_changed())
            entry.bind("<Return>", lambda _event: self.on_paste_changed())
        self.fields = {"items": items_var}

    def _build_paste_csv_fields(self) -> None:
        ttk.Label(self.body, text="CSV列引用").grid(row=0, column=0, sticky="w")
        expr_var = tk.StringVar(value="input.A")
        entry = ttk.Entry(self.body, textvariable=expr_var)
        entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(6, 12))
        ttk.Label(self.body, text="固定文件：input.csv").grid(row=0, column=4, columnspan=2, sticky="w")
        hint = ttk.Label(self.body, text="写法：input.A/B/C（列名）")
        hint.grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))
        if self.on_paste_changed:
            expr_var.trace_add("write", lambda *_args: self.on_paste_changed())
            entry.bind("<FocusOut>", lambda _event: self.on_paste_changed())
            entry.bind("<Return>", lambda _event: self.on_paste_changed())
        self.fields = {"input_expr": expr_var}

    def _build_key_fields(self) -> None:
        ttk.Label(self.body, text="按键组合").grid(row=0, column=0, sticky="w")
        combo_var = tk.StringVar(value="tab")
        common_keys = [
            "win",
            "enter",
            "tab",
            "shift+tab",
            "esc",
            "backspace",
            "delete",
            "space",
            "up",
            "down",
            "left",
            "right",
            "home",
            "end",
            "pageup",
            "pagedown",
            "ctrl+c",
            "ctrl+v",
            "ctrl+x",
            "ctrl+a",
            "ctrl+s",
            "alt+tab",
            "ctrl+shift+s",
        ]
        ttk.Combobox(
            self.body,
            textvariable=combo_var,
            values=common_keys,
            width=18,
        ).grid(row=0, column=1, columnspan=5, sticky="ew", padx=(6, 0))
        hint = ttk.Label(self.body, text="常用：enter / tab / shift+tab / ctrl+c / ctrl+v / alt+tab / esc / space")
        hint.grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))
        self.fields = {"combo": combo_var}

    def _build_wait_fields(self) -> None:
        ttk.Label(self.body, text="等待秒数").grid(row=0, column=0, sticky="w")
        seconds_var = tk.StringVar(value="1")
        ttk.Entry(self.body, textvariable=seconds_var, width=8).grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.fields = {"seconds": seconds_var}

    def _build_section_fields(self) -> None:
        if not self._section_name_cache:
            if callable(self.get_next_section_name):
                self._section_name_cache = self.get_next_section_name()
            else:
                self._section_name_cache = "阶段1"
        ttk.Label(self.body, text="阶段名", foreground="#8E0C0C").grid(row=0, column=0, sticky="w")
        title_var = tk.StringVar(value=self._section_name_cache)
        ttk.Entry(self.body, textvariable=title_var, width=18).grid(row=0, column=1, sticky="w", padx=(6, 12))
        ttk.Label(self.body, text="备注", foreground="#8E0C0C").grid(row=0, column=2, sticky="w")
        note_var = tk.StringVar(value="")
        ttk.Entry(self.body, textvariable=note_var).grid(row=0, column=3, columnspan=3, sticky="ew", padx=(6, 0))
        title_var.trace_add("write", lambda *_args: self._on_section_title_changed(title_var))
        self.fields = {"title": title_var, "note": note_var}

    def _build_subloop_fields(self) -> None:
        ttk.Label(self.body, text="循环次数").grid(row=0, column=0, sticky="w")
        loop_var = tk.StringVar(value="2")
        ttk.Entry(self.body, textvariable=loop_var, width=8).grid(row=0, column=1, sticky="w", padx=(6, 8))
        hint = ttk.Label(self.body, text="仅支持 1 层循环，循环范围到“退出循环”步骤前")
        hint.grid(row=0, column=2, columnspan=4, sticky="w")
        self.fields = {"loop_count": loop_var}

    def _on_section_title_changed(self, title_var: tk.StringVar) -> None:
        title = title_var.get().strip()
        self._section_name_cache = title or self._section_name_cache
        self.title_var.set(title or "阶段")

    def to_dict(self) -> Dict[str, Any]:
        step_type = self.type_var.get()
        if step_type == "click":
            click_mode = self.fields["click_mode"].get().strip().lower()
            clicks_map = {"single": 1, "double": 2, "triple": 3}
            return {
                "type": "click",
                "x": int(float(self.fields["x"].get())),
                "y": int(float(self.fields["y"].get())),
                "button": self.fields["button"].get(),
                "clicks": clicks_map.get(click_mode, 1),
            }
        if step_type == "paste":
            items = self.parse_paste_items_text(self.fields["items"].get())
            if not items:
                raise ValueError("文本数组不能为空，请使用逗号分隔，例如：hi, ho")
            return {"type": "paste", "items": items}
        if step_type == "paste-csv":
            expr = self.fields["input_expr"].get().strip()
            if not expr:
                raise ValueError("paste-csv 输入项不能为空，例如：input.A")
            if not expr.lower().startswith("input."):
                raise ValueError("paste-csv 写法必须以 input. 开头，例如：input.A/B")
            cols_raw = expr.split(".", 1)[1].strip()
            columns = [col.strip() for col in cols_raw.split("/") if col.strip()]
            if not columns:
                raise ValueError("请至少填写一个列名，例如：input.A")
            normalized = f"input.{'/'.join(columns)}"
            return {"type": "paste-csv", "input_expr": normalized, "columns": columns}
        if step_type == "key":
            combo = self.fields["combo"].get().strip()
            if not combo:
                raise ValueError("按键组合不能为空")
            return {"type": "key", "combo": combo}
        if step_type == "section":
            title = self.fields["title"].get().strip() or "阶段"
            note = self.fields["note"].get().strip()
            return {"type": "section", "title": title, "note": note}
        if step_type in ("loop", "subloop"):
            loop_count = int(float(self.fields["loop_count"].get()))
            if loop_count <= 0:
                raise ValueError("子循环次数必须大于 0")
            return {"type": "loop", "loop_count": loop_count}
        seconds = float(self.fields["seconds"].get())
        if seconds < 0:
            raise ValueError("等待秒数不能小于 0")
        return {"type": "wait", "seconds": seconds}

    def set_from_dict(self, data: Dict[str, Any]) -> None:
        step_type = data.get("type", "click")
        if step_type == "subloop":
            step_type = "loop"
        self.type_var.set(step_type)
        self.refresh_fields()
        if step_type == "click":
            self.fields["x"].set(str(data.get("x", 0)))
            self.fields["y"].set(str(data.get("y", 0)))
            button = str(data.get("button", "left")).lower()
            if button not in ("left", "right"):
                button = "left"
            self.fields["button"].set(button)
            clicks = int(data.get("clicks", 1))
            click_mode = "single"
            if clicks >= 3:
                click_mode = "triple"
            elif clicks == 2:
                click_mode = "double"
            self.fields["click_mode"].set(click_mode)
        elif step_type == "paste":
            items = [str(item) for item in data.get("items", []) if str(item).strip()]
            self.fields["items"].set(", ".join(items))
        elif step_type == "paste-csv":
            expr = str(data.get("input_expr", "")).strip()
            if not expr:
                columns = [str(col).strip() for col in data.get("columns", []) if str(col).strip()]
                expr = f"input.{'/'.join(columns)}" if columns else "input.A"
            self.fields["input_expr"].set(expr)
        elif step_type == "key":
            self.fields["combo"].set(data.get("combo", "tab"))
        elif step_type == "section":
            title = str(data.get("title", "阶段")).strip() or "阶段"
            self._section_name_cache = title
            self.fields["title"].set(title)
            self.fields["note"].set(str(data.get("note", "")))
            self.title_var.set(title)
        elif step_type == "loop":
            count = int(float(data.get("loop_count", 2)))
            if count <= 0:
                count = 1
            self.fields["loop_count"].set(str(count))
        else:
            self.fields["seconds"].set(str(data.get("seconds", 1)))


class App:
    def __init__(self) -> None:
        _enable_high_dpi_awareness()
        _set_windows_app_user_model_id()
        self.root = tk.Tk()
        self.root.title(f"蜘蛛侠Spiderman+{APP_VERSION}")
        self.window_icon_image: Any | None = None
        self._hicon_small: int | None = None
        self._hicon_big: int | None = None
        self._temp_icon_path: Path | None = None
        self._apply_window_icon()
        self.window_width = 980
        self.window_height = 760
        self._configure_window_and_fonts()

        self.stop_event = threading.Event()
        self.hotkey_stop_event = threading.Event()
        self.hotkey_thread: threading.Thread | None = None
        self.hotkey_thread_id: int | None = None
        self.worker: threading.Thread | None = None
        self.ui_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.step_editors: List[StepEditor] = []
        self.selected_editor: StepEditor | None = None
        self._render_pending = False
        self._loading_task = False
        self._resize_after_id: str | None = None
        self._resize_idle_after_id: str | None = None
        self._is_resizing = False
        self._last_resize_size: Tuple[int, int] | None = None
        self._last_side_layout: Tuple[int, int] | None = None
        self._scrollregion_after_id: str | None = None
        self._last_scrollregion: Tuple[int, int, int, int] | None = None
        self._last_canvas_width: int | None = None
        self._recording_clicks = False
        self._recording_thread: threading.Thread | None = None
        self.info_window: tk.Toplevel | None = None
        self.info_avatar_image: Any | None = None
        self.info_avatar_alt_image: Any | None = None
        self.info_avatar_label: ttk.Label | None = None
        self.info_avatar_showing_alt = False

        self.task_name_var = tk.StringVar(value=f"Auto{date.today():%Y%m%d}")
        self.loop_count_var = tk.StringVar(value="1")
        self.delay_var = tk.StringVar(value="0.3")
        self.status_var = tk.StringVar(value="就绪")

        self._build_ui()
        self._load_task_list()
        self.root.after_idle(lambda: self.add_step({"type": "click", "x": 0, "y": 0, "button": "left"}))
        self.root.after(100, self._poll_ui_queue)
        self.root.bind("<Configure>", self._on_root_resize)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._start_global_hotkey_listener()

    def _apply_window_icon(self) -> None:
        try:
            from PIL import Image, ImageTk

            # Title-bar icon from embedded JFIF bytes.
            jfif_raw = base64.b64decode(SPIDERMAN_JFIF_BASE64)
            pil_img = Image.open(io.BytesIO(jfif_raw)).convert("RGBA")
            pil_img = pil_img.resize((64, 64), Image.Resampling.LANCZOS)
            self.window_icon_image = ImageTk.PhotoImage(pil_img)
            self.root.iconphoto(True, self.window_icon_image)
        except Exception:
            pass

        # Win32 taskbar APIs require a file path; write embedded ICO to temp file.
        icon_path = self._get_embedded_icon_file_path()
        if icon_path is None:
            return
        try:
            self.root.iconbitmap(default=str(icon_path))
        except Exception:
            pass
        self._force_windows_taskbar_icon(icon_path)

    def _get_embedded_icon_file_path(self) -> Path | None:
        if self._temp_icon_path and self._temp_icon_path.exists():
            return self._temp_icon_path
        try:
            ico_raw = base64.b64decode(SPIDERMAN_ICO_BASE64)
            tmp_dir = Path(tempfile.gettempdir())
            tmp_path = tmp_dir / f"spiderman_icon_{APP_VERSION.replace('.', '_')}.ico"
            tmp_path.write_bytes(ico_raw)
            self._temp_icon_path = tmp_path
            return tmp_path
        except Exception:
            return None

    def _force_windows_taskbar_icon(self, icon_path: Path) -> None:
        try:
            user32 = ctypes.windll.user32
            hwnd = int(self.root.winfo_id())
            flags = LR_LOADFROMFILE | LR_DEFAULTSIZE
            small = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 16, 16, flags)
            big = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 32, 32, flags)
            if small:
                self._hicon_small = int(small)
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small)
            if big:
                self._hicon_big = int(big)
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        except Exception:
            pass

    def _configure_window_and_fonts(self) -> None:
        screen_width = max(self.root.winfo_screenwidth(), 1024)
        screen_height = max(self.root.winfo_screenheight(), 768)

        target_width = max(980, int(screen_width * 0.62))
        target_height = max(720, int(screen_height * 0.78))
        target_width = min(target_width, screen_width - 80)
        target_height = min(target_height, screen_height - 100)

        min_width = min(960, max(820, int(screen_width * 0.48)))
        min_height = min(700, max(620, int(screen_height * 0.55)))

        self.window_width = target_width
        self.window_height = target_height

        offset_x = max((screen_width - target_width) // 2, 0)
        offset_y = max((screen_height - target_height) // 2, 0)
        self.root.geometry(f"{target_width}x{target_height}+{offset_x}+{offset_y}")
        self.root.minsize(min_width, min_height)

        font_size = 13
        if screen_height >= 1600:
            font_size = 16
        elif screen_height >= 1440:
            font_size = 15
        elif screen_height >= 1200:
            font_size = 14
        elif screen_height <= 900 or screen_width <= 1366:
            font_size = 11
        self._apply_font_scale(font_size)

    def _apply_font_scale(self, size: int) -> None:
        self.default_font = tkfont.Font(family="Segoe UI", size=size, weight="bold")
        self.section_font = tkfont.Font(family="Segoe UI", size=size + 2, weight="bold")

        self.root.option_add("*Font", self.default_font)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TLabel", font=self.default_font)
        style.configure("TButton", font=self.default_font)
        style.configure("TEntry", font=self.default_font)
        style.configure("TCombobox", font=self.default_font)
        style.configure("TLabelframe.Label", font=self.default_font)
        style.configure("TCheckbutton", font=self.default_font)
        style.configure("TRadiobutton", font=self.default_font)

        style.configure("Section.TLabelframe.Label", font=self.section_font)
        style.configure("StepTitle.TLabel", font=self.default_font, background="#F7F9FC", foreground="#1B2430")
        style.configure("StepTitleSubloop.TLabel", font=self.default_font, background="#DCE8F8", foreground="#1B2430")
        style.configure("StepTitleSelected.TLabel", font=self.default_font, background="#FBE7E7", foreground="#1B2430")
        style.configure("SectionStepTitle.TLabel", font=self.default_font, background="#F7F9FC", foreground="#8E0C0C")
        style.configure("SectionStepTitleSubloop.TLabel", font=self.default_font, background="#DCE8F8", foreground="#8E0C0C")
        style.configure("SectionStepTitleSelected.TLabel", font=self.default_font, background="#FBE7E7", foreground="#8E0C0C")
        style.configure("SubloopStepTitle.TLabel", font=self.default_font, background="#F7F9FC", foreground="#1B4B7A")
        style.configure("SubloopStepTitleSubloop.TLabel", font=self.default_font, background="#DCE8F8", foreground="#1B4B7A")
        style.configure("SubloopStepTitleSelected.TLabel", font=self.default_font, background="#FBE7E7", foreground="#1B4B7A")
        # Readability-first palette with subtle Spider-Man accents.
        style.configure("Main.TFrame", background="#EEF2F7")
        style.configure("StepCard.TFrame", background="#F7F9FC")
        style.configure("StepCardSubloop.TFrame", background="#DCE8F8")
        style.configure("StepCardSelected.TFrame", background="#FBE7E7")
        style.configure("Footer.TFrame", background="#FFFFFF")
        style.configure("PanelInner.TFrame", background="#FFFFFF")
        style.configure("StepCardText.TLabel", background="#F7F9FC", foreground="#1B2430")
        style.configure("StepCardSubloopText.TLabel", background="#DCE8F8", foreground="#1B2430")
        style.configure("StepCardSelectedText.TLabel", background="#FBE7E7", foreground="#1B2430")
        style.configure("PanelText.TLabel", background="#FFFFFF", foreground="#1B2430")
        style.configure("Info.TLabel", background="#EEF2F7", foreground="#1B2430")
        style.configure("Panel.TLabelframe", background="#FFFFFF", bordercolor="#CDD5E0", borderwidth=1)
        style.configure("Panel.TLabelframe.Label", background="#FFFFFF", foreground="#8E0C0C", font=self.section_font)
        style.configure("TLabel", background="#FFFFFF", foreground="#1B2430")
        style.configure("TButton", background="#D8E0EA", foreground="#1B2430", borderwidth=1)
        style.map("TButton", background=[("active", "#C8D2DE"), ("pressed", "#B4C1CF")])
        style.configure("AccentRun.TButton", background="#B11313", foreground="#FFFFFF", borderwidth=1)
        style.map("AccentRun.TButton", background=[("active", "#CC2626"), ("pressed", "#8E0C0C")])
        style.configure("AccentAdd.TButton", background="#B11313", foreground="#FFFFFF", borderwidth=1)
        style.map("AccentAdd.TButton", background=[("active", "#CC2626"), ("pressed", "#8E0C0C")])
        style.configure("AccentSubloop.TButton", background="#4E8FD3", foreground="#FFFFFF", borderwidth=1)
        style.map("AccentSubloop.TButton", background=[("active", "#6FA8E2"), ("pressed", "#3D79BE")])
        style.configure("StepRound.TButton", background="#E9EEF5", foreground="#1F3C5C", borderwidth=1, padding=(4, 1))
        style.map("StepRound.TButton", background=[("active", "#DFE7F2"), ("pressed", "#D2DEEC")])
        style.configure("TEntry", fieldbackground="#FFFFFF", foreground="#101114")
        style.configure("TCombobox", fieldbackground="#FFFFFF", foreground="#101114")
        style.configure("StepType.TCombobox", background="#FFFFFF", fieldbackground="#FFFFFF", foreground="#1B2430")
        style.map(
            "StepType.TCombobox",
            background=[("readonly", "#FFFFFF"), ("focus", "#FFFFFF")],
            fieldbackground=[("readonly", "#FFFFFF"), ("focus", "#FFFFFF")],
            foreground=[("readonly", "#1B2430"), ("focus", "#1B2430"), ("!focus", "#1B2430")],
            selectbackground=[("readonly", "#FFFFFF"), ("focus", "#FFFFFF")],
            selectforeground=[("readonly", "#1B2430"), ("focus", "#1B2430")],
        )

    def _build_ui(self) -> None:
        self.root.configure(bg="#E9EDF4")

        container = ttk.Frame(self.root, padding=8, style="Main.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.columnconfigure(1, weight=0)
        container.rowconfigure(0, weight=0)
        container.rowconfigure(1, weight=1)

        canvas_frame = ttk.LabelFrame(container, text="步骤列表", padding=6, style="Panel.TLabelframe")
        canvas_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(1, weight=1)
        self.canvas_frame = canvas_frame

        list_toolbar = ttk.Frame(canvas_frame, style="StepCard.TFrame")
        list_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        list_toolbar.columnconfigure(3, weight=1)
        ttk.Button(list_toolbar, text="新增步骤", command=self.add_step, style="AccentAdd.TButton", width=10).grid(row=0, column=0, sticky="w")
        ttk.Button(list_toolbar, text="子循环", command=self.add_subloop, style="AccentSubloop.TButton", width=10).grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Button(list_toolbar, text="录制点击链", command=self.record_click_chain, width=10).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(list_toolbar, text="清空全部", command=self.clear_all_steps, width=10).grid(row=0, column=4, sticky="e", padx=(8, 0))
        ttk.Button(list_toolbar, text="input模板", command=self.generate_input_template, width=10).grid(row=0, column=5, sticky="e", padx=(8, 0))

        self.canvas = tk.Canvas(canvas_frame, highlightthickness=0, bg="#FFFFFF")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.steps_container = ttk.Frame(self.canvas, style="PanelInner.TFrame")
        self.steps_window = self.canvas.create_window((0, 0), window=self.steps_container, anchor="nw")
        self.steps_container.columnconfigure(0, weight=1)
        self.steps_container.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_steps_window)

        config = ttk.LabelFrame(container, text="任务配置", padding=6, style="Panel.TLabelframe")
        config.grid(row=0, column=1, sticky="new")
        config.columnconfigure(0, weight=1)

        config_actions = ttk.Frame(config, style="PanelInner.TFrame")
        config_actions.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        config_actions.columnconfigure(0, weight=1)
        config_actions.columnconfigure(1, weight=1)
        ttk.Button(config_actions, text="运 行", command=self.run_task, style="AccentRun.TButton", width=8).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(config_actions, text="Info", command=self.show_info, width=6).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        config_row = ttk.Frame(config, style="PanelInner.TFrame")
        config_row.grid(row=1, column=0, sticky="ew")
        config_row.columnconfigure(1, weight=1)

        ttk.Label(config_row, text="任务名", style="PanelText.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(config_row, textvariable=self.task_name_var, width=14).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Label(config_row, text="循环次数 K", style="PanelText.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(config_row, textvariable=self.loop_count_var, width=7).grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))
        ttk.Label(config_row, text="步骤间隔(s)", style="PanelText.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(config_row, textvariable=self.delay_var, width=7).grid(row=2, column=1, sticky="ew", padx=(6, 0), pady=(6, 0))

        side = ttk.LabelFrame(container, text="保存/加载", padding=8, style="Panel.TLabelframe")
        side.grid(row=1, column=1, sticky="nsew", pady=(8, 0))
        side.configure(width=300)
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(2, weight=1)
        side.configure(height=max(260, int(self.window_height * 0.55)))
        self.side_frame = side

        config.configure(width=300)
        self.config_frame = config

        self._bind_non_step_focus(config)
        self._bind_non_step_focus(side)

        button_row = ttk.Frame(side, style="Main.TFrame")
        button_row.grid(row=0, column=0, sticky="ew")
        ttk.Button(button_row, text="保存", command=self.save_task, width=8).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(button_row, text="另存为", command=self.save_task_as, width=8).grid(row=0, column=1, sticky="ew", padx=(0, 4))
        ttk.Button(button_row, text="加载", command=self.load_selected_task, width=8).grid(row=0, column=2, sticky="ew")
        button_row.columnconfigure((0, 1, 2), weight=1)

        ttk.Label(side, text="已保存任务").grid(row=1, column=0, sticky="w", pady=(10, 4))
        self.task_list = tk.Listbox(side, height=8, width=18, bg="#FFFFFF", fg="#1B2430", selectbackground="#C9D7E8")
        self.task_list.configure(borderwidth=0, relief="flat", highlightthickness=1, highlightbackground="#CDD5E0")
        self.task_list.grid(row=2, column=0, sticky="nsew")
        ttk.Button(side, text="刷新列表", command=self._load_task_list, width=12).grid(row=3, column=0, sticky="ew", pady=(8, 0))

        bottom = ttk.Frame(container, style="Footer.TFrame")
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(
            bottom,
            text=(
                f"启动快捷键：{GLOBAL_START_HOTKEY_LABEL}\n"
                f"全局叫停快捷键：{GLOBAL_STOP_HOTKEY_LABEL}\n"
                f"录制结束快捷键：{GLOBAL_RECORD_STOP_HOTKEY_LABEL}"
            ),
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))
        ttk.Button(bottom, text="停止", command=self.stop_task).grid(row=1, column=0, sticky="w")
        ttk.Label(bottom, textvariable=self.status_var, justify="right", anchor="e").grid(row=1, column=1, sticky="e")

    def _on_root_resize(self, event) -> None:
        if event.widget is not self.root:
            return
        if not hasattr(self, "side_frame"):
            return

        new_size = (int(event.width), int(event.height))
        if self._last_resize_size == new_size:
            return

        self._last_resize_size = new_size
        self._is_resizing = True
        if self._resize_idle_after_id:
            try:
                self.root.after_cancel(self._resize_idle_after_id)
            except Exception:
                pass
        self._resize_idle_after_id = self.root.after(180, self._on_resize_idle)
        if self._resize_after_id:
            try:
                self.root.after_cancel(self._resize_after_id)
            except Exception:
                pass
        # Keep drag-time work tiny; apply full updates after user pauses.
        self._resize_after_id = self.root.after(120, self._apply_responsive_layout)

    def _on_resize_idle(self) -> None:
        self._resize_idle_after_id = None
        self._is_resizing = False
        self._apply_responsive_layout()
        self._flush_scroll_region()

    def _apply_responsive_layout(self) -> None:
        self._resize_after_id = None
        if not hasattr(self, "side_frame"):
            return

        height = max(self.root.winfo_height(), 1)
        side_width = 300
        side_height = max(260, int(height * 0.50))
        next_layout = (side_width, side_height)
        if self._last_side_layout == next_layout:
            return
        self._last_side_layout = next_layout
        self.side_frame.configure(width=side_width)
        self.side_frame.configure(height=side_height)
        if hasattr(self, "config_frame"):
            self.config_frame.configure(width=side_width)

    def _bind_non_step_focus(self, widget: tk.Widget) -> None:
        widget.bind("<Button-1>", self._on_non_step_focus, add="+")
        widget.bind("<FocusIn>", self._on_non_step_focus, add="+")
        for child in widget.winfo_children():
            self._bind_non_step_focus(child)

    def _on_non_step_focus(self, _event=None):
        # Only clear step selection visuals here; do not steal focus from config inputs.
        self.set_selected_editor(None)
        for item in self.step_editors:
            item.clear_input_selection()
        return None

    def _start_global_hotkey_listener(self) -> None:
        if self.hotkey_thread and self.hotkey_thread.is_alive():
            return
        self.hotkey_stop_event.clear()
        self.hotkey_thread = threading.Thread(target=self._hotkey_listener_loop, daemon=True)
        self.hotkey_thread.start()

    def _hotkey_listener_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.hotkey_thread_id = int(kernel32.GetCurrentThreadId())

        mod_alt = 0x0001
        mod_control = 0x0002
        mod_shift = 0x0004
        vk_f5 = 0x74
        vk_w = 0x57
        vk_r = 0x52
        stop_modifiers = mod_alt | mod_control | mod_shift
        start_modifiers = mod_control
        record_stop_modifiers = mod_alt | mod_control | mod_shift

        start_ok = bool(user32.RegisterHotKey(None, HOTKEY_ID_START, start_modifiers, vk_f5))
        stop_ok = bool(user32.RegisterHotKey(None, HOTKEY_ID_STOP, stop_modifiers, vk_w))
        record_stop_ok = bool(user32.RegisterHotKey(None, HOTKEY_ID_RECORD_STOP, record_stop_modifiers, vk_r))
        if not start_ok:
            self.ui_queue.put(("status", f"启动热键注册失败：{GLOBAL_START_HOTKEY_LABEL}"))
        if not stop_ok:
            self.ui_queue.put(("status", f"全局热键注册失败：{GLOBAL_STOP_HOTKEY_LABEL}"))
        if not record_stop_ok:
            self.ui_queue.put(("status", f"录制结束热键注册失败：{GLOBAL_RECORD_STOP_HOTKEY_LABEL}"))
        if not start_ok and not stop_ok and not record_stop_ok:
            return

        msg = wintypes.MSG()
        try:
            while not self.hotkey_stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result <= 0:
                    break
                if msg.message == WM_HOTKEY:
                    hotkey_id = int(msg.wParam)
                    if hotkey_id == HOTKEY_ID_START:
                        self.ui_queue.put(("hotkey_start", None))
                    elif hotkey_id == HOTKEY_ID_STOP:
                        self.ui_queue.put(("hotkey_stop", None))
                    elif hotkey_id == HOTKEY_ID_RECORD_STOP:
                        self.ui_queue.put(("hotkey_record_stop", None))
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID_START)
            user32.UnregisterHotKey(None, HOTKEY_ID_STOP)
            user32.UnregisterHotKey(None, HOTKEY_ID_RECORD_STOP)

    def _stop_global_hotkey_listener(self) -> None:
        self.hotkey_stop_event.set()
        if self.hotkey_thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.hotkey_thread_id, WM_QUIT, 0, 0)
        if self.hotkey_thread and self.hotkey_thread.is_alive():
            self.hotkey_thread.join(timeout=0.5)

    def _on_close(self) -> None:
        self._stop_global_hotkey_listener()
        if self._temp_icon_path and self._temp_icon_path.exists():
            try:
                self._temp_icon_path.unlink()
            except Exception:
                pass
        self.root.destroy()

    def _to_circular_photo(self, pil_img, target_size: int, fill_ratio: float = 1.0, apply_circle_mask: bool = True, keep_full_frame: bool = False):
        from PIL import Image, ImageTk, ImageDraw, ImageChops

        resampling = getattr(Image, "Resampling", Image)
        if keep_full_frame:
            src = pil_img.convert("RGBA")
            side = max(src.width, src.height)
            frame = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            ox = (side - src.width) // 2
            oy = (side - src.height) // 2
            frame.paste(src, (ox, oy), src)
            pil_img = frame
        else:
            side = min(pil_img.width, pil_img.height)
            left = max((pil_img.width - side) // 2, 0)
            top_offset = max((pil_img.height - side) // 2, 0)
            pil_img = pil_img.crop((left, top_offset, left + side, top_offset + side)).convert("RGBA")
        side = pil_img.width

        if fill_ratio > 1.0:
            # Zoom into the center before circular mask so the logo appears truly filled.
            inner = max(8, int(side / fill_ratio))
            inner = min(inner, side)
            offset = (side - inner) // 2
            pil_img = pil_img.crop((offset, offset, offset + inner, offset + inner))
            pil_img = pil_img.resize((side, side), resampling.LANCZOS)
        elif 0.0 < fill_ratio < 1.0:
            # Shrink content to reveal more complete source image inside circle.
            inner = max(8, int(side * fill_ratio))
            reduced = pil_img.resize((inner, inner), resampling.LANCZOS)
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            offset = (side - inner) // 2
            canvas.paste(reduced, (offset, offset), reduced)
            pil_img = canvas

        if apply_circle_mask:
            mask = Image.new("L", (side, side), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, side - 1, side - 1), fill=255)
            # Preserve existing transparency (e.g. from shrink canvas) to avoid black artifacts.
            alpha = pil_img.getchannel("A")
            pil_img.putalpha(ImageChops.multiply(alpha, mask))

        pil_img = pil_img.resize((target_size, target_size), resampling.LANCZOS)
        return ImageTk.PhotoImage(pil_img)

    def _load_spiderman_icon_photo(self, target_size: int):
        try:
            from PIL import Image

            raw = base64.b64decode(SPIDERMAN_JFIF_BASE64)
            pil_img = Image.open(io.BytesIO(raw)).convert("RGBA")
            # Convert near-white background to transparent for a cleaner toggle icon.
            px = pil_img.load()
            w, h = pil_img.size
            for y in range(h):
                for x in range(w):
                    r, g, b, a = px[x, y]
                    if r >= 245 and g >= 245 and b >= 245:
                        px[x, y] = (r, g, b, 0)
            # Keep full icon content; avoid extra circular clipping.
            return self._to_circular_photo(
                pil_img,
                target_size,
                fill_ratio=0.8,
                apply_circle_mask=False,
                keep_full_frame=True,
            )
        except Exception:
            pass
        return None

    def _toggle_info_avatar(self, _event=None) -> None:
        if not self.info_avatar_label:
            return
        if self.info_avatar_alt_image is None or self.info_avatar_image is None:
            return

        self.info_avatar_showing_alt = not self.info_avatar_showing_alt
        next_image = self.info_avatar_alt_image if self.info_avatar_showing_alt else self.info_avatar_image
        self.info_avatar_label.configure(image=next_image)

    def show_info(self) -> None:
        if self.info_window and self.info_window.winfo_exists():
            self.info_window.deiconify()
            self.info_window.lift()
            self.info_window.focus_force()
            return

        win = tk.Toplevel(self.root)
        self.info_window = win
        win.title(f"{APP_NAME} Info {APP_VERSION}")
        win.transient(self.root)
        win.resizable(False, False)
        win.configure(bg="#EDF2F8")
        win.protocol("WM_DELETE_WINDOW", self._close_info_window)

        panel = ttk.Frame(win, style="Main.TFrame", padding=12)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)

        top = ttk.Frame(panel, style="Main.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)

        avatar_box = ttk.Frame(top, style="Main.TFrame", padding=0)
        avatar_box.grid(row=0, column=1, sticky="ne", padx=(12, 0))

        try:
            img = tk.PhotoImage(data=AVATAR_PNG_BASE64, format="png")
            target_h = int(self.default_font.metrics("linespace") * 3.0)
            target_h = max(target_h, 56)
            if img.height() > target_h:
                target_w = max(1, int(img.width() * target_h / img.height()))
                try:
                    from PIL import Image, ImageTk, ImageDraw

                    raw = base64.b64decode(AVATAR_PNG_BASE64)
                    pil_img = Image.open(io.BytesIO(raw)).convert("RGBA")
                    # Force a circular avatar with transparent outer area.
                    side = min(pil_img.width, pil_img.height)
                    left = max((pil_img.width - side) // 2, 0)
                    top_offset = max((pil_img.height - side) // 2, 0)
                    pil_img = pil_img.crop((left, top_offset, left + side, top_offset + side))
                    # Auto-trim near-black outer edge while preserving most facial area.
                    gray = pil_img.convert("L")
                    non_dark = gray.point(lambda p: 255 if p > 28 else 0)
                    bbox = non_dark.getbbox()
                    if bbox:
                        # Keep a small margin to avoid clipping facial edges.
                        bw = bbox[2] - bbox[0]
                        bh = bbox[3] - bbox[1]
                        pad = max(2, int(min(bw, bh) * 0.04))
                        x0 = max(0, bbox[0] - pad)
                        y0 = max(0, bbox[1] - pad)
                        x1 = min(pil_img.width, bbox[2] + pad)
                        y1 = min(pil_img.height, bbox[3] + pad)
                        pil_img = pil_img.crop((x0, y0, x1, y1))
                    side = min(pil_img.width, pil_img.height)
                    left = max((pil_img.width - side) // 2, 0)
                    top_offset = max((pil_img.height - side) // 2, 0)
                    pil_img = pil_img.crop((left, top_offset, left + side, top_offset + side))
                    mask = Image.new("L", (side, side), 0)
                    draw = ImageDraw.Draw(mask)
                    draw.ellipse((0, 0, side - 1, side - 1), fill=255)
                    pil_img.putalpha(mask)
                    # Make near-black pixels on the outer circular band fully transparent.
                    px = pil_img.load()
                    center = (side - 1) / 2.0
                    radius = center
                    ring = max(1.5, side * 0.06)
                    ring_inner = max(0.0, radius - ring)
                    dark_threshold = 56
                    for y in range(side):
                        dy = y - center
                        for x in range(side):
                            dx = x - center
                            dist = (dx * dx + dy * dy) ** 0.5
                            if dist < ring_inner or dist > radius:
                                continue
                            r, g, b, a = px[x, y]
                            if a == 0:
                                continue
                            if max(r, g, b) <= dark_threshold:
                                px[x, y] = (r, g, b, 0)
                    resampling = getattr(Image, "Resampling", Image)
                    pil_img = pil_img.resize((target_h, target_h), resampling.LANCZOS)
                    img = ImageTk.PhotoImage(pil_img)
                except Exception:
                    ratio = max(1, (img.height() + target_h - 1) // target_h)
                    img = img.subsample(ratio, ratio)
            self.info_avatar_image = img
            self.info_avatar_alt_image = self._load_spiderman_icon_photo(target_h)
            self.info_avatar_showing_alt = False
            self.info_avatar_label = ttk.Label(avatar_box, image=img, style="Info.TLabel", cursor="hand2")
            self.info_avatar_label.grid(row=0, column=0, sticky="w")
            self.info_avatar_label.bind("<Button-1>", self._toggle_info_avatar)
        except Exception:
            ttk.Label(avatar_box, text="头像加载失败", style="Info.TLabel").grid(row=0, column=0, sticky="w")

        info = ttk.Frame(top, style="Main.TFrame")
        info.grid(row=0, column=0, sticky="nsew")
        info.columnconfigure(1, weight=1)

        today = date.today().isoformat()
        profile_items = [
            ("项目名：", APP_NAME),
            ("功能简介：", "Windows系统自动化流程编排工具"),
            ("版本号：", APP_VERSION),
            ("作者：", APP_AUTHOR),
            ("日期：", today),
        ]
        usage = (
            "1. 编排步骤并配置 click/paste/paste-csv/key/wait。\n"
            "2. 设置循环次数 K 与步骤间隔，形成执行策略。\n"
            "3. 运行任务，并通过保存/加载实现复用。"
        )
        framework = (
            "- UI：Tkinter + ttk\n"
            "- 自动化：pyautogui\n"
            "- 剪贴板：pyperclip\n"
            "- 数据：JSON + input.csv"
        )
        changes = (
            "- V2.3：新增录制点击链，左键采样后按 Enter 或快捷键结束并插入步骤。\n"
            "- V2.3：logo 资源内嵌，窗口/任务栏图标与彩蛋切换不依赖外部文件。\n"
            "- V2.3：窗口缩放与步骤渲染继续优化，保持轻量化体验。"
        )

        ttk.Label(info, text="开发者信息", style="Section.TLabelframe.Label").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))
        for idx, (key_text, value_text) in enumerate(profile_items, start=1):
            ttk.Label(info, text=key_text, anchor="e", style="Info.TLabel").grid(row=idx, column=0, sticky="e", padx=(0, 6), pady=(2, 0))
            ttk.Label(info, text=value_text, anchor="w", style="Info.TLabel").grid(row=idx, column=1, sticky="w", pady=(2, 0))

        content = ttk.Frame(panel, style="Main.TFrame")
        content.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        content.columnconfigure(0, weight=1)

        ttk.Label(content, text="项目使用方式", style="Section.TLabelframe.Label").grid(row=0, column=0, sticky="w")
        ttk.Label(content, text=usage, justify="left", wraplength=560, style="Info.TLabel").grid(row=1, column=0, sticky="w", pady=(2, 10))

        ttk.Label(content, text="框架简介", style="Section.TLabelframe.Label").grid(row=2, column=0, sticky="w")
        ttk.Label(content, text=framework, justify="left", style="Info.TLabel").grid(row=3, column=0, sticky="w", pady=(2, 10))

        ttk.Label(content, text="版本变更", style="Section.TLabelframe.Label").grid(row=4, column=0, sticky="w")
        ttk.Label(content, text=changes, justify="left", wraplength=560, style="Info.TLabel").grid(row=5, column=0, sticky="w")

        ttk.Button(content, text="关闭", command=self._close_info_window, width=8).grid(row=6, column=0, sticky="e", pady=(12, 0))

        # Keep Info popup centered on screen.
        win.update_idletasks()
        popup_w = win.winfo_reqwidth()
        popup_h = win.winfo_reqheight()
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        pos_x = max((screen_w - popup_w) // 2, 0)
        pos_y = max((screen_h - popup_h) // 2, 0)
        win.geometry(f"+{pos_x}+{pos_y}")

    def _close_info_window(self) -> None:
        if self.info_window and self.info_window.winfo_exists():
            self.info_window.destroy()
        self.info_window = None
        self.info_avatar_image = None
        self.info_avatar_alt_image = None
        self.info_avatar_label = None
        self.info_avatar_showing_alt = False

    def _update_scroll_region(self, _event=None) -> None:
        if self._is_resizing:
            return
        if self._scrollregion_after_id:
            return
        self._scrollregion_after_id = self.root.after_idle(self._flush_scroll_region)

    def _flush_scroll_region(self) -> None:
        self._scrollregion_after_id = None
        if not hasattr(self, "canvas") or not self.canvas.winfo_exists():
            return
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        if self._last_scrollregion == bbox:
            return
        self._last_scrollregion = bbox
        self.canvas.configure(scrollregion=bbox)

    def _resize_steps_window(self, event) -> None:
        width = int(event.width)
        if self._last_canvas_width == width:
            return
        if self._is_resizing and self._last_canvas_width is not None and abs(width - self._last_canvas_width) < 8:
            return
        self._last_canvas_width = width
        self.canvas.itemconfigure(self.steps_window, width=width)

    def add_step(self, data: Dict[str, Any] | None = None, index: int | None = None) -> StepEditor:
        if index is None:
            if self.selected_editor in self.step_editors:
                selected_index = self.step_editors.index(self.selected_editor)
                insert_at = selected_index + 1
            else:
                insert_at = len(self.step_editors)
        else:
            insert_at = index

        def delete_current() -> None:
            self.remove_step(editor)

        def move_up() -> None:
            if editor not in self.step_editors:
                return
            pos = self.step_editors.index(editor)
            if pos > 0:
                self.step_editors[pos - 1], self.step_editors[pos] = self.step_editors[pos], self.step_editors[pos - 1]
                self._request_render_steps()

        def move_down() -> None:
            if editor not in self.step_editors:
                return
            pos = self.step_editors.index(editor)
            if pos < len(self.step_editors) - 1:
                self.step_editors[pos + 1], self.step_editors[pos] = self.step_editors[pos], self.step_editors[pos + 1]
                self._request_render_steps()

        def duplicate_current() -> None:
            self.duplicate_step(editor)

        editor = StepEditor(
            self.steps_container,
            insert_at,
            delete_current,
            move_up,
            move_down,
            duplicate_current,
            self.set_selected_editor,
            self._on_step_widget_mousewheel,
            self._sync_loop_count_from_paste,
            self._next_section_name,
        )
        self.step_editors.insert(insert_at, editor)
        if data:
            editor.set_from_dict(data)
        self.set_selected_editor(editor)
        self._request_render_steps()
        return editor

    def set_selected_editor(self, editor: StepEditor | None, focus_widget: tk.Widget | None = None) -> None:
        self.selected_editor = editor if editor in self.step_editors else None
        for item in self.step_editors:
            is_selected = item is self.selected_editor
            item.set_selected(is_selected)
            if not is_selected:
                item.clear_input_selection()

        # When selection is driven by non-step controls, avoid retaining text selection traces.
        if focus_widget is None and self.selected_editor:
            self.selected_editor.clear_input_selection()

        # When focusing a step on the left, clear right-side input selection highlight.
        if self.selected_editor:
            self._clear_non_step_input_selection()

    def _clear_non_step_input_selection(self) -> None:
        def _walk(widget: tk.Widget) -> None:
            for child in widget.winfo_children():
                try:
                    if isinstance(child, (ttk.Entry, tk.Entry)):
                        child.selection_clear()
                        child.icursor(tk.END)
                    elif isinstance(child, ttk.Combobox):
                        # Do not call selection_clear on readonly combobox; keep displayed value stable.
                        child.icursor(tk.END)
                except Exception:
                    pass
                _walk(child)

        for panel_name in ("config_frame", "side_frame"):
            panel = getattr(self, panel_name, None)
            if panel is not None:
                _walk(panel)

    def _release_all_focus_marks(self) -> None:
        self.set_selected_editor(None)
        for item in self.step_editors:
            item.clear_input_selection()
        try:
            self.root.focus_set()
        except Exception:
            pass

    def _is_inside_subloop_at(self, index: int) -> bool:
        inside = False
        for i in range(max(0, index)):
            step_type = self.step_editors[i].type_var.get()
            if step_type in ("loop", "subloop"):
                inside = True
                continue
            if step_type == "section":
                title_var = self.step_editors[i].fields.get("title")
                title = title_var.get().strip() if title_var else ""
                if inside and title == "退出循环":
                    inside = False
        return inside

    def add_subloop(self) -> None:
        if self.selected_editor in self.step_editors:
            selected_index = self.step_editors.index(self.selected_editor)
            insert_at = selected_index + 1
        else:
            insert_at = len(self.step_editors)

        if self._is_inside_subloop_at(insert_at):
            messagebox.showerror("配置错误", "仅支持 1 层子循环，不能在子循环内再新建子循环")
            return

        loop_editor = self.add_step({"type": "loop", "loop_count": 2}, index=insert_at)
        first_inner = self.add_step({"type": "click", "x": 0, "y": 0, "button": "left", "clicks": 1}, index=insert_at + 1)
        self.add_step({"type": "section", "title": "退出循环", "note": ""}, index=insert_at + 2)
        self.set_selected_editor(first_inner if first_inner in self.step_editors else loop_editor)

    def record_click_chain(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "任务执行中，不能录制点击链")
            return
        if self._recording_clicks:
            self._recording_clicks = False
            self.status_var.set(f"录制结束请求已发送：{GLOBAL_RECORD_STOP_HOTKEY_LABEL}")
            return
        if self.selected_editor not in self.step_editors:
            messagebox.showinfo("提示", "请先选择一个聚焦步骤，再开始录制")
            return

        anchor_index = self.step_editors.index(self.selected_editor)
        self._recording_clicks = True
        self.status_var.set(f"录制中：左键点击采样，按 Enter 或 {GLOBAL_RECORD_STOP_HOTKEY_LABEL} 结束")
        self.root.withdraw()
        self._recording_thread = threading.Thread(
            target=self._record_click_chain_worker,
            args=(anchor_index,),
            daemon=True,
        )
        self._recording_thread.start()

    def _record_click_chain_worker(self, anchor_index: int) -> None:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        try:
            user32 = ctypes.windll.user32
            vk_lbutton = 0x01
            vk_return = 0x0D
            points: List[Tuple[int, int]] = []
            lbutton_prev = False
            enter_prev = False
            started_at = time.perf_counter()

            while True:
                lbutton_down = bool(user32.GetAsyncKeyState(vk_lbutton) & 0x8000)
                if lbutton_down and not lbutton_prev:
                    pt = POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    points.append((int(pt.x), int(pt.y)))

                enter_down = bool(user32.GetAsyncKeyState(vk_return) & 0x8000)
                if time.perf_counter() - started_at >= 0.25 and enter_down and not enter_prev:
                    break

                lbutton_prev = lbutton_down
                enter_prev = enter_down
                time.sleep(0.01)

            self.ui_queue.put(("record_done", {"anchor_index": anchor_index, "points": points}))
        except Exception as exc:
            self.ui_queue.put(("record_error", str(exc)))

    def _insert_recorded_clicks(self, anchor_index: int, points: List[Tuple[int, int]]) -> None:
        if not points:
            self.status_var.set("录制结束：未记录到点击")
            return

        insert_at = min(max(0, anchor_index + 1), len(self.step_editors))
        last_editor = None
        for x, y in points:
            last_editor = self.add_step(
                {"type": "click", "x": int(x), "y": int(y), "button": "left", "clicks": 1},
                index=insert_at,
            )
            insert_at += 1

        if last_editor in self.step_editors:
            self.set_selected_editor(last_editor)
        self.status_var.set(f"录制完成：已插入 {len(points)} 个点击步骤")

    def duplicate_step(self, editor: StepEditor) -> None:
        if editor not in self.step_editors:
            return
        index = self.step_editors.index(editor) + 1
        self.add_step(editor.to_dict(), index=index)

    def clear_step(self, editor: StepEditor) -> None:
        if editor not in self.step_editors:
            return
        editor.reset_to_default()
        editor.clear_values()
        self._sync_loop_count_from_paste()

    def clear_all_steps(self) -> None:
        for editor in self.step_editors:
            editor.frame.destroy()
        self.step_editors.clear()
        self.selected_editor = None
        self._sync_loop_count_from_paste()
        self._request_render_steps()

    def generate_input_template(self) -> None:
        path = APP_DIR / "input.csv"
        if path.exists():
            overwrite = messagebox.askyesno("提示", "input.csv 已存在，是否覆盖？")
            if not overwrite:
                return
        rows = [
            ["1", "红色", "苹果"],
            ["2", "蓝色", "香蕉"],
            ["3", "绿色", "橙子"],
            ["4", "黄色", "葡萄"],
            ["5", "黑色", "西瓜"],
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        self.status_var.set("已生成 input.csv 模板")

    def remove_step(self, editor: StepEditor) -> None:
        if editor in self.step_editors:
            if editor is self.selected_editor:
                self.selected_editor = None
            self.step_editors.remove(editor)
            try:
                editor.frame.destroy()
            except tk.TclError:
                pass
            self._sync_loop_count_from_paste()
            self._request_render_steps()

    def _next_section_name(self) -> str:
        max_no = 0
        pattern = re.compile(r"^阶段\s*(\d+)$")
        for editor in self.step_editors:
            if editor.type_var.get() != "section":
                continue
            title_var = editor.fields.get("title")
            if not title_var:
                continue
            title = title_var.get().strip()
            match = pattern.match(title)
            if not match:
                continue
            max_no = max(max_no, int(match.group(1)))
        return f"阶段{max_no + 1}"

    def _sync_loop_count_from_paste(self) -> None:
        if self._loading_task:
            return
        max_size = 0
        for idx, editor in enumerate(self.step_editors):
            if self._is_inside_subloop_at(idx):
                continue
            if editor.type_var.get() not in ("paste", "paste-csv"):
                continue
            if editor.type_var.get() == "paste":
                items_var = editor.fields.get("items")
                if not items_var:
                    continue
                items = StepEditor.parse_paste_items_text(items_var.get())
            else:
                try:
                    items = self._load_input_csv_rows()
                except Exception:
                    items = []
            max_size = max(max_size, len(items))
        if max_size > 0:
            self.loop_count_var.set(str(max_size))

    def _request_render_steps(self) -> None:
        if self._render_pending:
            return
        if not self.root.winfo_exists():
            return

        self._render_pending = True
        self.root.after_idle(self._render_steps)

    def _render_steps(self) -> None:
        self._render_pending = False
        if not self.steps_container.winfo_exists():
            return

        for child in self.steps_container.winfo_children():
            try:
                child.grid_forget()
            except tk.TclError:
                pass
        visible_editors = [editor for editor in self.step_editors if editor.frame.winfo_exists()]
        self.step_editors = visible_editors
        indents = self._compute_step_indents()
        inside_loop = False
        loop_body_step_no = 0
        for index, editor in enumerate(visible_editors):
            step_type = editor.type_var.get()
            if step_type in ("loop", "subloop"):
                inside_loop = True
                loop_body_step_no = 0
                editor.refresh_index(index)
            elif inside_loop and step_type == "section":
                title_var = editor.fields.get("title")
                title = title_var.get().strip() if title_var else ""
                editor.refresh_index(index)
                if title == "退出循环":
                    inside_loop = False
            elif inside_loop:
                loop_body_step_no += 1
                editor.refresh_index(index, loop_body_step_no=loop_body_step_no)
            else:
                editor.refresh_index(index)
            editor.set_selected(editor is self.selected_editor)
            try:
                indent = 0
                if index < len(indents):
                    indent = indents[index]
                editor.set_in_subloop_body(indent > 0)
                editor.frame.grid(row=index, column=0, sticky="ew", pady=2, padx=(indent * 20, 0))
            except tk.TclError:
                continue
        try:
            self.steps_container.update_idletasks()
        except tk.TclError:
            return
        self._update_scroll_region()

    def _compute_step_indents(self) -> List[int]:
        indents: List[int] = []
        inside_subloop = False
        for editor in self.step_editors:
            step_type = editor.type_var.get()
            if step_type in ("loop", "subloop"):
                indents.append(0)
                inside_subloop = True
                continue

            if step_type == "section":
                title_var = editor.fields.get("title")
                title = title_var.get().strip() if title_var else ""
                if inside_subloop and title == "退出循环":
                    indents.append(0)
                    inside_subloop = False
                    continue

            indents.append(1 if inside_subloop else 0)
        return indents

    def collect_task(self) -> Dict[str, Any]:
        name = self.task_name_var.get().strip()
        if not name:
            raise ValueError("任务名不能为空")
        loop_count = int(float(self.loop_count_var.get()))
        if loop_count <= 0:
            raise ValueError("循环次数必须大于 0")
        delay_seconds = float(self.delay_var.get())
        if delay_seconds < 0:
            raise ValueError("步骤间隔不能小于 0")
        steps = [editor.to_dict() for editor in self.step_editors]
        self._validate_subloops(steps)
        if not steps:
            raise ValueError("至少要有一个步骤")
        executable_steps = [s for s in steps if s.get("type") not in ("section", "loop", "subloop")]
        if not executable_steps:
            raise ValueError("至少要有一个可执行步骤（click / paste / paste-csv / key / wait）")
        return {
            "version": 1,
            "name": name,
            "loop_count": loop_count,
            "delay_seconds": delay_seconds,
            "steps": steps,
        }

    def _validate_subloops(self, steps: List[Dict[str, Any]]) -> None:
        inside_subloop = False
        body_count = 0
        for step in steps:
            step_type = step.get("type")
            if step_type == "subloop":
                step_type = "loop"
            if step_type == "loop":
                if inside_subloop:
                    raise ValueError("仅支持 1 层子循环，检测到嵌套子循环")
                loop_count = int(step.get("loop_count", 1))
                if loop_count <= 0:
                    raise ValueError("子循环次数必须大于 0")
                inside_subloop = True
                body_count = 0
                continue

            if inside_subloop and step_type == "section" and str(step.get("title", "")).strip() == "退出循环":
                if body_count == 0:
                    raise ValueError("子循环不能为空，请在子循环中至少配置 1 个步骤")
                inside_subloop = False
                continue

            if inside_subloop and step_type in ("loop", "subloop"):
                raise ValueError("仅支持 1 层子循环，检测到嵌套子循环")
            if inside_subloop:
                body_count += 1

        if inside_subloop:
            raise ValueError("子循环缺少“退出循环”步骤")

    def _task_path(self, name: str) -> Path:
        safe = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", " ")).strip() or "task"
        return TASK_DIR / f"{safe}.json"

    def save_task(self) -> None:
        try:
            task = self.collect_task()
            path = self._task_path(task["name"])
            path.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status_var.set(f"已保存：{path.name}")
            self._load_task_list()
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    def save_task_as(self) -> None:
        path = filedialog.asksaveasfilename(
            title="另存为任务",
            initialdir=str(TASK_DIR),
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json")],
        )
        if not path:
            return
        try:
            task = self.collect_task()
            target = Path(path)
            target.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status_var.set(f"已另存为：{target.name}")
            self._load_task_list()
        except Exception as exc:
            messagebox.showerror("另存失败", str(exc))

    def load_selected_task(self) -> None:
        self._release_all_focus_marks()
        selection = self.task_list.curselection()
        if not selection:
            messagebox.showinfo("提示", "先选择一个已保存任务")
            return
        name = self.task_list.get(selection[0])
        if name.startswith(BUILTIN_LIST_PREFIX):
            builtin_name = name[len(BUILTIN_LIST_PREFIX) :]
            data = BUILTIN_TASKS.get(builtin_name)
            if not data:
                messagebox.showerror("加载失败", f"内置任务不存在：{builtin_name}")
                return
            self.load_task_data(data, f"{builtin_name}.json")
            self._release_all_focus_marks()
            return
        path = TASK_DIR / name
        self.load_task_file(path)
        self._release_all_focus_marks()

    def load_task_file(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.load_task_data(data, path.name)
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))

    def load_task_data(self, data: Dict[str, Any], source_name: str) -> None:
        self._loading_task = True
        try:
            self.task_name_var.set(data.get("name", source_name.rsplit(".", 1)[0]))
            self.loop_count_var.set(str(data.get("loop_count", 1)))
            self.delay_var.set(str(data.get("delay_seconds", 0.3)))
            for editor in self.step_editors:
                editor.frame.destroy()
            self.step_editors.clear()
            for step in data.get("steps", []):
                self.add_step(step)
        finally:
            self._loading_task = False
        self.status_var.set(f"已加载：{source_name}")

    def _load_task_list(self) -> None:
        self.task_list.delete(0, tk.END)
        for builtin_name in sorted(BUILTIN_TASKS):
            self.task_list.insert(tk.END, f"{BUILTIN_LIST_PREFIX}{builtin_name}")
        for path in sorted(TASK_DIR.glob("*.json")):
            self.task_list.insert(tk.END, path.name)

    def run_task(self) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "任务正在执行中")
            return
        try:
            task = self.collect_task()
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return

        preloaded_csv_rows: List[Dict[str, str]] = []
        referenced_columns = self._collect_referenced_input_columns(task.get("steps", []))
        if referenced_columns:
            try:
                preloaded_csv_rows = self._load_input_csv_rows()
            except Exception as exc:
                messagebox.showerror("输入数据错误", str(exc))
                return

            proceed, detail_lines = self._build_input_reference_prompt(preloaded_csv_rows, referenced_columns)
            if not proceed:
                messagebox.showerror("输入引用错误", "未检测到可用列引用，请检查 paste-csv 配置")
                return

            detail_text = "\n".join(detail_lines)
            ok = messagebox.askyesno(
                "运行前确认",
                f"检测到 input 引用：\n{detail_text}\n\n是否继续执行？",
            )
            if not ok:
                self.status_var.set("已取消执行")
                return

        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run_task_worker, args=(task, preloaded_csv_rows), daemon=True)
        self.worker.start()
        self._hide_window()

    def _collect_referenced_input_columns(self, steps: List[Dict[str, Any]]) -> List[str]:
        columns: List[str] = []
        seen = set()
        for step in steps:
            if step.get("type") != "paste-csv":
                continue
            raw_columns = [str(col).strip() for col in step.get("columns", []) if str(col).strip()]
            if not raw_columns:
                expr = str(step.get("input_expr", "")).strip()
                if expr.lower().startswith("input."):
                    raw_columns = [col.strip() for col in expr.split(".", 1)[1].split("/") if col.strip()]
            for col in raw_columns:
                key = col.upper() if len(col) == 1 and col.isalpha() else col
                if key not in seen:
                    seen.add(key)
                    columns.append(key)
        return columns

    def _build_input_reference_prompt(
        self, csv_rows: List[Dict[str, str]], referenced_columns: List[str]
    ) -> Tuple[bool, List[str]]:
        if not referenced_columns:
            return False, []

        counts: Dict[str, int] = {col: 0 for col in referenced_columns}
        for row in csv_rows:
            for col in referenced_columns:
                if col in row:
                    counts[col] += 1

        lines = [f"{col} 列共 {counts[col]} 行" for col in referenced_columns]
        unique_counts = set(counts.values())
        if len(unique_counts) > 1:
            lines.append("注意：各列行数不相等，空缺部分会按空字符串处理（不填入内容）。")
        return True, lines

    def _hide_window(self) -> None:
        self.root.iconify()

    def _on_step_widget_mousewheel(self, event=None):
        if not hasattr(self, "canvas"):
            return "break"
        delta = getattr(event, "delta", 0)
        if delta == 0:
            return "break"
        units = -1 if delta > 0 else 1
        self.canvas.yview_scroll(units, "units")
        return "break"

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(100, lambda: self.root.attributes("-topmost", False))

    def stop_task(self) -> None:
        self.stop_event.set()
        self.status_var.set("请求停止中")

    def _run_task_worker(self, task: Dict[str, Any], preloaded_csv_rows: List[Dict[str, str]] | None = None) -> None:
        try:
            loop_count = int(task["loop_count"])
            delay_seconds = float(task["delay_seconds"])
            steps = task["steps"]
            if preloaded_csv_rows is None:
                csv_rows = self._load_input_csv_rows() if any(step.get("type") == "paste-csv" for step in steps) else []
            else:
                csv_rows = preloaded_csv_rows
            total = 0
            started_at = time.perf_counter()
            completed_loops = 0
            subloop_runs = 0
            subloop_total_seconds = 0.0
            subloop_runs_plan = loop_count * sum(
                max(1, int(step.get("loop_count", 1)))
                for step in steps
                if step.get("type") in ("loop", "subloop")
            )
            for loop_index in range(loop_count):
                if self.stop_event.is_set():
                    break
                self.ui_queue.put(("status", f"执行第 {loop_index + 1}/{loop_count} 轮"))
                step_index = 0
                while step_index < len(steps):
                    if self.stop_event.is_set():
                        break
                    step = steps[step_index]
                    step_type = step.get("type")
                    if step_type == "subloop":
                        step_type = "loop"
                    if step_type == "loop":
                        exit_index = self._find_subloop_exit_index(steps, step_index)
                        body_steps = steps[step_index + 1 : exit_index]
                        sub_count = max(1, int(step.get("loop_count", 1)))
                        for sub_index in range(sub_count):
                            sub_started_at = time.perf_counter()
                            logical_loop_index = loop_index * sub_count + sub_index
                            for inner in body_steps:
                                if self.stop_event.is_set():
                                    break
                                if inner.get("type") == "section":
                                    continue
                                self._execute_step(inner, logical_loop_index, csv_rows)
                                total += 1
                                self.ui_queue.put(
                                    ("status", f"主循环 {loop_index + 1}/{loop_count}，子循环 {sub_index + 1}/{sub_count}")
                                )
                                if delay_seconds > 0:
                                    time.sleep(delay_seconds)
                            subloop_total_seconds += max(0.0, time.perf_counter() - sub_started_at)
                            subloop_runs += 1
                            if self.stop_event.is_set():
                                break
                        step_index = exit_index + 1
                        continue

                    if step_type == "section":
                        step_index += 1
                        continue

                    self._execute_step(step, loop_index, csv_rows)
                    total += 1
                    self.ui_queue.put(("status", f"已执行轮次 {loop_index + 1}，步骤 {step_index + 1}/{len(steps)}"))
                    if delay_seconds > 0:
                        time.sleep(delay_seconds)
                    step_index += 1
                if self.stop_event.is_set():
                    break
                completed_loops += 1

            elapsed_seconds = time.perf_counter() - started_at
            avg_loop_seconds = (elapsed_seconds / completed_loops) if completed_loops > 0 else 0.0
            avg_subloop_seconds = (subloop_total_seconds / subloop_runs) if subloop_runs > 0 else 0.0
            summary = (
                f"循环 {completed_loops}/{loop_count}，总时间 {elapsed_seconds:.2f}s，"
                f"平均循环 {avg_loop_seconds:.2f}s\n"
                f"子循环 {subloop_runs}/{subloop_runs_plan}，总时间 {subloop_total_seconds:.2f}s，"
                f"平均循环 {avg_subloop_seconds:.2f}s"
            )
            if self.stop_event.is_set():
                final = f"已停止，{summary}"
            else:
                final = f"执行完成，共 {total} 个步骤，{summary}"
            self.ui_queue.put(("status", final))
            self.ui_queue.put(("show_window", None))
        except Exception as exc:
            self.ui_queue.put(("error", str(exc)))

    def _find_subloop_exit_index(self, steps: List[Dict[str, Any]], start_index: int) -> int:
        for index in range(start_index + 1, len(steps)):
            step = steps[index]
            if step.get("type") == "section" and str(step.get("title", "")).strip() == "退出循环":
                return index
            if step.get("type") in ("loop", "subloop"):
                raise ValueError("仅支持 1 层子循环，检测到嵌套子循环")
        raise ValueError("子循环缺少“退出循环”步骤")

    def _execute_step(self, step: Dict[str, Any], loop_index: int = 0, csv_rows: List[Dict[str, str]] | None = None) -> None:
        pyautogui = self._get_pyautogui()
        step_type = step.get("type")
        if step_type == "click":
            clicks = max(1, min(3, int(step.get("clicks", 1))))
            button = str(step.get("button", "left")).lower()
            if button not in ("left", "right"):
                button = "left"
            pyautogui.click(
                x=int(step["x"]),
                y=int(step["y"]),
                button=button,
                clicks=clicks,
                interval=0.08 if clicks > 1 else 0.0,
            )
            return
        if step_type == "paste":
            pyperclip = self._get_pyperclip()
            items = step.get("items", [])
            if not items:
                return
            item = items[loop_index % len(items)]
            pyperclip.copy(item)
            time.sleep(0.05)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.05)
            return
        if step_type == "paste-csv":
            if not csv_rows:
                raise RuntimeError("未找到可用 input.csv 数据，请先点‘input模板’生成")
            columns = [str(col).strip() for col in step.get("columns", []) if str(col).strip()]
            if not columns:
                expr = str(step.get("input_expr", "")).strip()
                if not expr.lower().startswith("input."):
                    raise ValueError("paste-csv 配置错误：请输入 input.列名")
                columns = [col.strip() for col in expr.split(".", 1)[1].split("/") if col.strip()]
            if not columns:
                raise ValueError("paste-csv 配置错误：列名不能为空")

            row = csv_rows[loop_index % len(csv_rows)]
            pyperclip = self._get_pyperclip()
            for col in columns:
                # Be tolerant: missing column in a specific row is treated as empty text.
                key = col.upper() if len(col) == 1 and col.isalpha() else col
                pyperclip.copy(str(row.get(key, "")))
                time.sleep(0.05)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.05)
            return
        if step_type == "key":
            combo = [part.strip().lower() for part in step.get("combo", "").split("+") if part.strip()]
            if not combo:
                return
            if len(combo) == 1:
                pyautogui.press(combo[0])
            else:
                pyautogui.hotkey(*combo)
            return
        if step_type == "wait":
            time.sleep(float(step.get("seconds", 1)))
            return
        if step_type == "section":
            return
        raise ValueError(f"未知步骤类型：{step_type}")

    def _get_pyautogui(self):
        global _pyautogui
        if _pyautogui is None:
            try:
                import pyautogui as module
            except ImportError as exc:
                raise RuntimeError("缺少 pyautogui，请先安装依赖") from exc
            module.PAUSE = 0
            module.FAILSAFE = True
            _pyautogui = module
        return _pyautogui

    def _get_pyperclip(self):
        global _pyperclip
        if _pyperclip is None:
            try:
                import pyperclip as module
            except ImportError as exc:
                raise RuntimeError("缺少 pyperclip，请先安装依赖") from exc
            _pyperclip = module
        return _pyperclip

    def _load_input_csv_rows(self) -> List[Dict[str, str]]:
        path = APP_DIR / "input.csv"
        if not path.exists():
            raise FileNotFoundError("未找到 input.csv，请先点‘input模板’生成")

        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            source_rows: List[List[str]] = []
            for raw in reader:
                cleaned = [str(v).strip() for v in raw]
                if any(cleaned):
                    source_rows.append(cleaned)

        if not source_rows:
            raise ValueError("input.csv 没有数据行，请至少保留 1 行")

        start_index = 0
        first = [v.upper() for v in source_rows[0]]
        if len(first) >= 3 and first[0:3] == ["A", "B", "C"]:
            # Backward compatibility: support old template that included A/B/C header row.
            start_index = 1

        rows: List[Dict[str, str]] = []
        for raw in source_rows[start_index:]:
            item: Dict[str, str] = {}
            for idx, value in enumerate(raw):
                if idx < 26:
                    key = chr(ord("A") + idx)
                else:
                    key = f"COL{idx + 1}"
                item[key] = value
            if item:
                rows.append(item)

        if not rows:
            raise ValueError("input.csv 没有数据行，请至少保留 1 行")
        return rows

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "show_window":
                    self._show_window()
                elif kind == "hotkey_start":
                    if self.worker and self.worker.is_alive():
                        self.status_var.set("任务已在执行中")
                    else:
                        self.run_task()
                        self.status_var.set(f"已触发启动快捷键：{GLOBAL_START_HOTKEY_LABEL}")
                elif kind == "hotkey_stop":
                    if self.worker and self.worker.is_alive():
                        self.stop_task()
                        self.status_var.set(f"已触发全局叫停：{GLOBAL_STOP_HOTKEY_LABEL}")
                        self._show_window()
                elif kind == "hotkey_record_stop":
                    if self._recording_clicks:
                        self._recording_clicks = False
                        self.status_var.set(f"已触发录制结束：{GLOBAL_RECORD_STOP_HOTKEY_LABEL}")
                elif kind == "record_done":
                    self._recording_clicks = False
                    self._show_window()
                    anchor_index = int(payload.get("anchor_index", 0))
                    points = payload.get("points", [])
                    self._insert_recorded_clicks(anchor_index, points)
                elif kind == "record_error":
                    self._recording_clicks = False
                    self._show_window()
                    self.status_var.set("录制失败")
                    messagebox.showerror("录制失败", payload)
                elif kind == "error":
                    self.status_var.set("执行失败")
                    self._show_window()
                    messagebox.showerror("执行失败", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui_queue)

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            self._stop_global_hotkey_listener()


if __name__ == "__main__":
    App().run()
