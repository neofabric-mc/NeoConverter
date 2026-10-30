"""NeoConverter tkinter interface. All Tk operations stay on the main thread."""
from __future__ import annotations

from collections import Counter
import queue
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
import traceback

from converter import VERSION, collect_jars, convert_jar
from windows_drop import WindowsDrop

BG = "#f6f5f2"
INK = "#24272b"
MUTED = "#686d73"
RED = "#b73437"


class ConverterApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.paths = []
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.closing = False
        self.results = []
        self.drop = None
        self.root.title("NeoConverter")
        self.root.geometry("860x720")
        self.root.minsize(730, 610)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.callback_error
        self.recursive = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="等待添加 jar 文件")
        self.count = tk.StringVar(value="0 个文件")
        self._build()
        try:
            self.drop = WindowsDrop(self.root, self.add_paths, self.log)
        except Exception as exc:
            self.drop_caption.configure(text="也可以使用下方按钮选择文件或文件夹")
            self.log(f"[提示] 拖放不可用：{exc}")
        self._poll_id = self.root.after(80, self.poll)

    def _build(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Microsoft YaHei UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("TCheckbutton", background=BG, foreground=MUTED)
        style.configure("TButton", padding=(14, 6), background="#ffffff", foreground=INK)
        style.map("TButton", background=[("active", "#e9e7e2")])
        style.configure("Accent.TButton", background=RED, foreground="white", padding=(20, 7))
        style.map("Accent.TButton",
                  background=[("disabled", "#c8b3b2"), ("active", "#91282c")],
                  foreground=[("disabled", "#faf6f6")])
        style.configure("Horizontal.TProgressbar", background=RED, troughcolor="#e7e3dd", thickness=7)
        outer = ttk.Frame(self.root, padding=(28, 20))
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="NeoConverter", font=("Segoe UI", 22, "bold")).pack(side="left")
        ttk.Label(header, text=f"v{VERSION}  /  FABRIC → NEOFABRIC",
                  foreground=MUTED, font=("Segoe UI", 9)).pack(side="right", pady=(13, 0))
        ttk.Label(outer, text="补齐兼容标记，保留模组原本的样子。",
                  foreground=MUTED).pack(anchor="w", pady=(5, 13))

        drop_box = tk.Frame(outer, bg="#ffffff", highlightbackground="#d5c6c2", highlightthickness=1)
        drop_box.pack(fill="x")
        tk.Label(drop_box, text="↓", font=("Segoe UI", 22), bg="white", fg=RED).pack(pady=(8, 0))
        tk.Label(drop_box, text="把 jar 文件或文件夹拖到这里",
                 font=("Microsoft YaHei UI", 12, "bold"), bg="white", fg=INK).pack(pady=(0, 7))
        self.drop_caption = tk.Label(
            drop_box, text="支持多个文件 · 中文路径 · 输出与原文件同目录",
            font=("Microsoft YaHei UI", 9), bg="white", fg=MUTED
        )
        self.drop_caption.pack(pady=(0, 12))
        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(10, 6))
        self.files_button = ttk.Button(actions, text="选择文件", command=self.choose_files)
        self.files_button.pack(side="left")
        self.folder_button = ttk.Button(actions, text="选择文件夹", command=self.choose_folder)
        self.folder_button.pack(side="left", padx=(9, 0))
        self.clear_button = ttk.Button(actions, text="清空列表", command=self.clear)
        self.clear_button.pack(side="left", padx=(9, 0))
        self.recursive_check = ttk.Checkbutton(actions, text="包含子文件夹", variable=self.recursive)
        self.recursive_check.pack(side="right")
        line = ttk.Frame(outer)
        line.pack(fill="x", pady=(4, 5))
        ttk.Label(line, text="待转换", font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        ttk.Label(line, textvariable=self.count, foreground=MUTED).pack(side="right")
        list_frame = ttk.Frame(outer)
        list_frame.pack(fill="x")
        self.file_list = tk.Listbox(
            list_frame, height=3, relief="flat", bg="white", fg=INK,
            font=("Microsoft YaHei UI", 9), selectbackground="#ead8d5", activestyle="none"
        )
        scroll = ttk.Scrollbar(list_frame, command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=scroll.set)
        self.file_list.pack(side="left", fill="x", expand=True)
        scroll.pack(side="right", fill="y")
        progress_line = ttk.Frame(outer)
        progress_line.pack(fill="x", pady=(10, 6))
        ttk.Label(progress_line, textvariable=self.status, foreground=MUTED).pack(side="left")
        self.start_button = ttk.Button(
            progress_line, text="开始转换", style="Accent.TButton", command=self.start, state="disabled"
        )
        self.start_button.pack(side="right")
        self.progress = ttk.Progressbar(outer, mode="determinate", maximum=1)
        self.progress.pack(fill="x", pady=(0, 10))
        ttk.Label(outer, text="处理日志", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.log_box = ScrolledText(
            outer, height=5, wrap="word", relief="flat", background="#eeece7", foreground=INK,
            font=("Microsoft YaHei UI", 9), padx=10, pady=9, state="disabled"
        )
        self.footer = ttk.Label(
            outer, text="原文件不会被覆盖  ·  只添加标记，不修复版本、依赖或代码兼容性",
            foreground=MUTED, font=("Microsoft YaHei UI", 9)
        )
        self.footer.pack(side="bottom", anchor="w", pady=(10, 0))
        self.log_box.pack(fill="both", expand=True)

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", str(text) + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def choose_files(self):
        paths = filedialog.askopenfilenames(
            parent=self.root, title="选择 Fabric 模组",
            filetypes=[("Java 模组", "*.jar"), ("所有文件", "*.*")]
        )
        if paths:
            self.add_paths(paths)

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self.root, title="选择包含模组的文件夹")
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths):
        if self.busy:
            self.log("[提示] 正在转换，请完成后再添加文件")
            return
        combined, notes = collect_jars([*self.paths, *paths], recursive=self.recursive.get())
        self.paths = combined
        self.file_list.delete(0, "end")
        for path in self.paths:
            self.file_list.insert("end", str(path))
        for note in notes:
            self.log(f"[提示] {note}")
        self.count.set(f"{len(self.paths)} 个文件")
        self.status.set(f"已准备 {len(self.paths)} 个文件" if self.paths else "等待添加 jar 文件")
        self.start_button.configure(state="normal" if self.paths else "disabled")

    def clear(self):
        if not self.busy:
            self.paths.clear()
            self.file_list.delete(0, "end")
            self.count.set("0 个文件")
            self.status.set("等待添加 jar 文件")
            self.start_button.configure(state="disabled")
            self.progress["value"] = 0

    def start(self):
        if self.busy or not self.paths:
            return
        self.busy = True
        self.cancel.clear()
        self.results = []
        batch = tuple(self.paths)
        self.progress.configure(maximum=len(batch), value=0)
        self.status.set(f"转换中 0 / {len(batch)}")
        for widget in (
            self.files_button, self.folder_button, self.clear_button, self.recursive_check, self.start_button
        ):
            widget.configure(state="disabled")
        self.log(f"\n[开始] 共 {len(batch)} 个 jar")
        self.worker = threading.Thread(target=self._work, args=(batch,), name="NeoConverter-worker", daemon=False)
        self.worker.start()

    def _work(self, batch):
        try:
            for path in batch:
                if self.cancel.is_set():
                    break
                self.events.put(("result", convert_jar(path)))
        except Exception:
            self.events.put(("error", traceback.format_exc()))
        finally:
            self.events.put(("done", len(batch)))

    def poll(self):
        # Bound each UI tick so very large skip-heavy batches remain responsive.
        for _ in range(200):
            try:
                kind, value = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "result":
                self.results.append(value)
                self.log(value.log_line())
                if value.success:
                    self.log(f"    输出：{value.output}")
                self.progress["value"] = len(self.results)
                self.status.set(f"转换中 {len(self.results)} / {len(self.paths)}")
            elif kind == "error":
                self.log(f"[错误] 后台任务异常：{value}")
            elif kind == "done":
                self.busy = False
                successes = sum(item.success for item in self.results)
                skipped = len(self.results) - successes
                reasons = Counter(item.reason for item in self.results if not item.success)
                self.status.set(f"完成：成功 {successes} 个，跳过 {skipped} 个")
                summary = f"成功 {successes} 个\n跳过 {skipped} 个"
                if reasons:
                    summary += "\n\n跳过原因：\n" + "\n".join(f"• {reason[:180]}（{count} 个）" for reason, count in list(reasons.items())[:8])
                    if len(reasons) > 8:
                        summary += f"\n其余 {len(reasons) - 8} 类原因详见滚动日志。"
                self.log(f"[完成] 成功 {successes} 个，跳过 {skipped} 个")
                if self.closing:
                    self._destroy()
                    return
                for widget in (self.files_button, self.folder_button, self.clear_button, self.recursive_check):
                    widget.configure(state="normal")
                self.start_button.configure(state="normal" if self.paths else "disabled")
                # All individual reasons remain in the scrollable log.
                messagebox.showinfo("NeoConverter · 转换完成", summary, parent=self.root)
        self._poll_id = self.root.after(80, self.poll)

    def callback_error(self, exception_type, exception, tb):
        detail = "".join(traceback.format_exception(exception_type, exception, tb))
        self.log(f"[错误] 界面操作失败：{detail}")
        messagebox.showerror("NeoConverter", f"操作未完成：{exception}\n详情见处理日志。", parent=self.root)

    def close(self):
        if self.busy:
            if messagebox.askyesno(
                "NeoConverter", "正在转换。是否在当前文件处理完毕后关闭？", parent=self.root
            ):
                self.closing = True
                self.cancel.set()
                self.status.set("正在完成当前文件，请稍候…")
            return
        self._destroy()

    def _destroy(self):
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        if self.drop:
            self.drop.close()
        self.root.destroy()
