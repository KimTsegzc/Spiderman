"""SpiderMan V1.2.

Windows desktop automation tool with task editing, loop execution,
JSON save/load, and simple mouse/keyboard/wait actions.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk, filedialog

_pyautogui = None
_pyperclip = None


APP_DIR = Path(__file__).resolve().parent
TASK_DIR = APP_DIR / "tasks"
TASK_DIR.mkdir(exist_ok=True)
APP_VERSION = "v1.2"
APP_AUTHOR = "广州分行 xiexin1.gd"


class StepEditor:
    def __init__(self, master: tk.Widget, index: int, on_delete, on_move_up, on_move_down, on_duplicate, on_clear):
        self.master = master
        self.index = index
        self.on_delete = on_delete
        self.on_move_up = on_move_up
        self.on_move_down = on_move_down
        self.on_duplicate = on_duplicate
        self.on_clear = on_clear
        self.frame = ttk.Frame(master, padding=4, relief="groove", style="StepCard.TFrame")
        self.frame.columnconfigure(0, weight=1)

        header = ttk.Frame(self.frame, style="StepCard.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        self.title_var = tk.StringVar(value=f"步骤 {index + 1}")
        ttk.Label(header, textvariable=self.title_var, width=10).grid(row=0, column=0, sticky="w")
        self.type_var = tk.StringVar(value="click")
        type_box = ttk.Combobox(
            header,
            textvariable=self.type_var,
            values=["click", "paste", "key", "wait"],
            state="readonly",
            width=10,
        )
        type_box.grid(row=0, column=1, sticky="w")
        type_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_fields())

        buttons = ttk.Frame(header, style="StepCard.TFrame")
        buttons.grid(row=0, column=2, sticky="e")
        ttk.Button(buttons, text="上移", width=5, command=self.on_move_up).grid(row=0, column=0, padx=1)
        ttk.Button(buttons, text="下移", width=5, command=self.on_move_down).grid(row=0, column=1, padx=1)
        ttk.Button(buttons, text="复制", width=5, command=self.on_duplicate).grid(row=0, column=2, padx=1)
        ttk.Button(buttons, text="清空", width=5, command=self.on_clear).grid(row=0, column=3, padx=1)
        ttk.Button(buttons, text="删除", width=5, command=self.on_delete).grid(row=0, column=4, padx=1)

        self.body = ttk.Frame(self.frame, style="StepCard.TFrame")
        self.body.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.body.columnconfigure(1, weight=1)

        self.fields: Dict[str, Any] = {}
        self.refresh_fields()

    def refresh_index(self, index: int) -> None:
        self.index = index
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
            self.fields["items"].set('["文本1", "文本2"]')
        elif current == "key":
            self.fields["combo"].set("tab")
        else:
            self.fields["seconds"].set("1")

    def refresh_fields(self) -> None:
        current = self.type_var.get()
        self.clear_body()
        if current == "click":
            self._build_click_fields()
        elif current == "paste":
            self._build_paste_fields()
        elif current == "key":
            self._build_key_fields()
        else:
            self._build_wait_fields()

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
            values=["left", "right", "middle"],
            state="readonly",
            width=7,
        ).grid(
            row=0, column=5, sticky="w", padx=(4, 0)
        )
        self.fields = {"x": x_var, "y": y_var, "button": btn_var}

    def _build_paste_fields(self) -> None:
        ttk.Label(self.body, text='文本数组 JSON').grid(row=0, column=0, sticky="w")
        items_var = tk.StringVar(value='["文本1", "文本2"]')
        entry = ttk.Entry(self.body, textvariable=items_var)
        entry.grid(row=0, column=1, columnspan=5, sticky="ew", padx=(6, 0))
        self.fields = {"items": items_var}

    def _build_key_fields(self) -> None:
        ttk.Label(self.body, text="按键组合").grid(row=0, column=0, sticky="w")
        combo_var = tk.StringVar(value="tab")
        common_keys = [
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

    def to_dict(self) -> Dict[str, Any]:
        step_type = self.type_var.get()
        if step_type == "click":
            return {
                "type": "click",
                "x": int(float(self.fields["x"].get())),
                "y": int(float(self.fields["y"].get())),
                "button": self.fields["button"].get(),
            }
        if step_type == "paste":
            items = json.loads(self.fields["items"].get())
            if not isinstance(items, list):
                raise ValueError("文本数组必须是 JSON 数组")
            normalized = []
            for item in items:
                if not isinstance(item, str):
                    raise ValueError("文本数组中每一项都必须是字符串")
                normalized.append(item)
            return {"type": "paste", "items": normalized}
        if step_type == "key":
            combo = self.fields["combo"].get().strip()
            if not combo:
                raise ValueError("按键组合不能为空")
            return {"type": "key", "combo": combo}
        seconds = float(self.fields["seconds"].get())
        if seconds < 0:
            raise ValueError("等待秒数不能小于 0")
        return {"type": "wait", "seconds": seconds}

    def set_from_dict(self, data: Dict[str, Any]) -> None:
        step_type = data.get("type", "click")
        self.type_var.set(step_type)
        self.refresh_fields()
        if step_type == "click":
            self.fields["x"].set(str(data.get("x", 0)))
            self.fields["y"].set(str(data.get("y", 0)))
            self.fields["button"].set(data.get("button", "left"))
        elif step_type == "paste":
            self.fields["items"].set(json.dumps(data.get("items", []), ensure_ascii=False))
        elif step_type == "key":
            self.fields["combo"].set(data.get("combo", "tab"))
        else:
            self.fields["seconds"].set(str(data.get("seconds", 1)))


class App:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"蜘蛛侠 {APP_VERSION}")
        self.root.geometry("980x760")
        self.root.minsize(900, 660)

        self._apply_font_scale(16)

        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.ui_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.step_editors: List[StepEditor] = []
        self._render_pending = False

        self.task_name_var = tk.StringVar(value=f"Auto{date.today():%Y%m%d}")
        self.loop_count_var = tk.StringVar(value="1")
        self.delay_var = tk.StringVar(value="0.3")
        self.status_var = tk.StringVar(value="就绪")

        self._build_ui()
        self._load_task_list()
        self.root.after_idle(lambda: self.add_step({"type": "click", "x": 0, "y": 0, "button": "left"}))
        self.root.after(100, self._poll_ui_queue)

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
        # Readability-first palette with subtle Spider-Man accents.
        style.configure("Main.TFrame", background="#EEF2F7")
        style.configure("StepCard.TFrame", background="#F7F9FC")
        style.configure("Panel.TLabelframe", background="#FFFFFF", bordercolor="#CDD5E0", borderwidth=1)
        style.configure("Panel.TLabelframe.Label", background="#FFFFFF", foreground="#8E0C0C", font=self.section_font)
        style.configure("TLabel", background="#EEF2F7", foreground="#1B2430")
        style.configure("TButton", background="#D8E0EA", foreground="#1B2430", borderwidth=1)
        style.map("TButton", background=[("active", "#C8D2DE"), ("pressed", "#B4C1CF")])
        style.configure("AccentRun.TButton", background="#B11313", foreground="#FFFFFF", borderwidth=1)
        style.map("AccentRun.TButton", background=[("active", "#CC2626"), ("pressed", "#8E0C0C")])
        style.configure("AccentAdd.TButton", background="#B11313", foreground="#FFFFFF", borderwidth=1)
        style.map("AccentAdd.TButton", background=[("active", "#CC2626"), ("pressed", "#8E0C0C")])
        style.configure("TEntry", fieldbackground="#FFFFFF", foreground="#101114")
        style.configure("TCombobox", fieldbackground="#FFFFFF", foreground="#101114")

    def _build_ui(self) -> None:
        self.root.configure(bg="#E9EDF4")

        container = ttk.Frame(self.root, padding=8, style="Main.TFrame")
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        top = ttk.LabelFrame(container, text="任务配置", padding=12, style="Panel.TLabelframe")
        top.grid(row=0, column=0, sticky="ew")
        for col in range(9):
            top.columnconfigure(col, weight=1 if col in (1, 3, 5, 7) else 0)

        ttk.Label(top, text="任务名").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.task_name_var, width=18).grid(row=0, column=1, sticky="w", padx=(6, 18))
        ttk.Label(top, text="循环次数 K").grid(row=0, column=2, sticky="w")
        ttk.Entry(top, textvariable=self.loop_count_var, width=10).grid(row=0, column=3, sticky="w", padx=(6, 18))
        ttk.Label(top, text="步骤间隔(s)").grid(row=0, column=4, sticky="w")
        ttk.Entry(top, textvariable=self.delay_var, width=10).grid(row=0, column=5, sticky="w", padx=(6, 18))
        ttk.Button(top, text="运行", command=self.run_task, style="AccentRun.TButton").grid(row=0, column=7, sticky="e")
        ttk.Button(top, text="Info", command=self.show_info, width=6).grid(row=0, column=8, sticky="e", padx=(8, 0))

        middle = ttk.Frame(container, style="Main.TFrame")
        middle.grid(row=1, column=0, sticky="nsew", pady=(8, 8))
        middle.columnconfigure(0, weight=1)
        middle.columnconfigure(1, weight=0)
        middle.rowconfigure(0, weight=1)

        canvas_frame = ttk.LabelFrame(middle, text="步骤列表", padding=6, style="Panel.TLabelframe")
        canvas_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(1, weight=1)

        list_toolbar = ttk.Frame(canvas_frame, style="Main.TFrame")
        list_toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        list_toolbar.columnconfigure(0, weight=1)
        ttk.Button(list_toolbar, text="新增步骤", command=self.add_step, style="AccentAdd.TButton").grid(row=0, column=0, sticky="w")
        ttk.Button(list_toolbar, text="清空全部", command=self.clear_all_steps).grid(row=0, column=1, sticky="w", padx=(8, 0))

        self.canvas = tk.Canvas(canvas_frame, highlightthickness=0, bg="#F5F8FC")
        self.canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.steps_container = ttk.Frame(self.canvas)
        self.steps_window = self.canvas.create_window((0, 0), window=self.steps_container, anchor="nw")
        self.steps_container.columnconfigure(0, weight=1)
        self.steps_container.bind("<Configure>", self._update_scroll_region)
        self.canvas.bind("<Configure>", self._resize_steps_window)

        side = ttk.LabelFrame(middle, text="保存/加载", padding=8, style="Panel.TLabelframe")
        side.grid(row=0, column=1, sticky="nsew")
        side.configure(width=250)
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(2, weight=1)

        button_row = ttk.Frame(side, style="Main.TFrame")
        button_row.grid(row=0, column=0, sticky="ew")
        ttk.Button(button_row, text="保存", command=self.save_task, width=8).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(button_row, text="另存为", command=self.save_task_as, width=8).grid(row=0, column=1, sticky="ew", padx=(0, 4))
        ttk.Button(button_row, text="加载", command=self.load_selected_task, width=8).grid(row=0, column=2, sticky="ew")
        button_row.columnconfigure((0, 1, 2), weight=1)

        ttk.Label(side, text="已保存任务").grid(row=1, column=0, sticky="w", pady=(10, 4))
        self.task_list = tk.Listbox(side, height=14, width=18, bg="#FFFFFF", fg="#1B2430", selectbackground="#C9D7E8")
        self.task_list.grid(row=2, column=0, sticky="nsew")
        ttk.Button(side, text="刷新列表", command=self._load_task_list, width=12).grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(side, text="导出任务 JSON", command=self.export_task, width=12).grid(row=4, column=0, sticky="ew", pady=(6, 0))

        bottom = ttk.Frame(container, style="Main.TFrame")
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Button(bottom, text="停止", command=self.stop_task).grid(row=0, column=0, sticky="w")
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=1, sticky="e")

    def show_info(self) -> None:
        today = date.today().isoformat()
        info_text = (
            f"版本号：{APP_VERSION}\n"
            f"作者：{APP_AUTHOR}\n"
            f"日期：{today}\n\n"
            "版本变更简介：\n"
            "- V1.2：优化主题配色，红色仅用于关键操作按钮（运行/新增步骤）。\n"
            "- V1.2：新增 Info 面板，补充版本、使用方式和框架说明。\n"
            "- V1.2：增强步骤编辑体验（复制、清空、清空全部）。\n\n"
            "使用方式：\n"
            "1. 在步骤列表中新增并配置 click/paste/key/wait。\n"
            "2. 设定循环次数 K 与步骤间隔(s)。\n"
            "3. 点运行执行任务；可保存/加载任务 JSON 复用。\n\n"
            "框架简介：\n"
            "- UI：Tkinter + ttk（Windows 桌面）\n"
            "- 自动化：pyautogui（鼠标/键盘）\n"
            "- 剪贴板：pyperclip\n"
            "- 数据：JSON 任务文件"
        )
        messagebox.showinfo("蜘蛛侠 - Info", info_text)

    def _update_scroll_region(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_steps_window(self, event) -> None:
        self.canvas.itemconfigure(self.steps_window, width=event.width)

    def add_step(self, data: Dict[str, Any] | None = None, index: int | None = None) -> None:
        insert_at = len(self.step_editors) if index is None else index

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

        def clear_current() -> None:
            self.clear_step(editor)

        editor = StepEditor(
            self.steps_container,
            insert_at,
            delete_current,
            move_up,
            move_down,
            duplicate_current,
            clear_current,
        )
        self.step_editors.insert(insert_at, editor)
        if data:
            editor.set_from_dict(data)
        self._request_render_steps()

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

    def clear_all_steps(self) -> None:
        for editor in self.step_editors:
            editor.frame.destroy()
        self.step_editors.clear()
        self._request_render_steps()

    def remove_step(self, editor: StepEditor) -> None:
        if editor in self.step_editors:
            self.step_editors.remove(editor)
            self._request_render_steps()

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
        for index, editor in enumerate(visible_editors):
            editor.refresh_index(index)
            try:
                editor.frame.grid(row=index, column=0, sticky="ew", pady=6)
            except tk.TclError:
                continue
        try:
            self.steps_container.update_idletasks()
        except tk.TclError:
            return
        self._update_scroll_region()

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
        if not steps:
            raise ValueError("至少要有一个步骤")
        return {
            "version": 1,
            "name": name,
            "loop_count": loop_count,
            "delay_seconds": delay_seconds,
            "steps": steps,
        }

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

    def export_task(self) -> None:
        try:
            task = self.collect_task()
            path = filedialog.asksaveasfilename(
                title="导出任务 JSON",
                initialdir=str(APP_DIR),
                defaultextension=".json",
                filetypes=[("JSON 文件", "*.json")],
            )
            if not path:
                return
            Path(path).write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
            self.status_var.set(f"已导出：{Path(path).name}")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    def load_selected_task(self) -> None:
        selection = self.task_list.curselection()
        if not selection:
            messagebox.showinfo("提示", "先选择一个已保存任务")
            return
        name = self.task_list.get(selection[0])
        path = TASK_DIR / name
        self.load_task_file(path)

    def load_task_file(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.task_name_var.set(data.get("name", path.stem))
            self.loop_count_var.set(str(data.get("loop_count", 1)))
            self.delay_var.set(str(data.get("delay_seconds", 0.3)))
            for editor in self.step_editors:
                editor.frame.destroy()
            self.step_editors.clear()
            for step in data.get("steps", []):
                self.add_step(step)
            self.status_var.set(f"已加载：{path.name}")
        except Exception as exc:
            messagebox.showerror("加载失败", str(exc))

    def _load_task_list(self) -> None:
        self.task_list.delete(0, tk.END)
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
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run_task_worker, args=(task,), daemon=True)
        self.worker.start()
        self._hide_window()

    def _hide_window(self) -> None:
        self.root.iconify()

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(100, lambda: self.root.attributes("-topmost", False))

    def stop_task(self) -> None:
        self.stop_event.set()
        self.status_var.set("请求停止中")

    def _run_task_worker(self, task: Dict[str, Any]) -> None:
        try:
            loop_count = int(task["loop_count"])
            delay_seconds = float(task["delay_seconds"])
            steps = task["steps"]
            total = 0
            started_at = time.perf_counter()
            completed_loops = 0
            for loop_index in range(loop_count):
                if self.stop_event.is_set():
                    break
                self.ui_queue.put(("status", f"执行第 {loop_index + 1}/{loop_count} 轮"))
                for step_index, step in enumerate(steps, start=1):
                    if self.stop_event.is_set():
                        break
                    self._execute_step(step, loop_index)
                    total += 1
                    self.ui_queue.put(("status", f"已执行轮次 {loop_index + 1}，步骤 {step_index}/{len(steps)}"))
                    if delay_seconds > 0:
                        time.sleep(delay_seconds)
                if self.stop_event.is_set():
                    break
                completed_loops += 1

            elapsed_seconds = time.perf_counter() - started_at
            avg_loop_seconds = (elapsed_seconds / completed_loops) if completed_loops > 0 else 0.0
            summary = (
                f"循环 {completed_loops}/{loop_count}，总时间 {elapsed_seconds:.2f}s，"
                f"平均循环 {avg_loop_seconds:.2f}s"
            )
            if self.stop_event.is_set():
                final = f"已停止，{summary}"
            else:
                final = f"执行完成，共 {total} 个步骤，{summary}"
            self.ui_queue.put(("status", final))
            self.ui_queue.put(("show_window", None))
        except Exception as exc:
            self.ui_queue.put(("error", str(exc)))

    def _execute_step(self, step: Dict[str, Any], loop_index: int = 0) -> None:
        pyautogui = self._get_pyautogui()
        step_type = step.get("type")
        if step_type == "click":
            pyautogui.click(x=int(step["x"]), y=int(step["y"]), button=step.get("button", "left"))
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

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "show_window":
                    self._show_window()
                elif kind == "error":
                    self.status_var.set("执行失败")
                    self._show_window()
                    messagebox.showerror("执行失败", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_ui_queue)

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
