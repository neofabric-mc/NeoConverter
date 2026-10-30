import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import zipfile

from app import ConverterApp


@unittest.skipUnless(os.name == "nt", "Windows native UI tests")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.root = tk.Tk()
        self.app = ConverterApp(self.root)
        self.root.withdraw()

    def tearDown(self):
        if self.app.busy:
            self.app.cancel.set()
            self.app.worker.join(timeout=10)
        self.app._destroy()
        self.tmp.cleanup()

    def fixture(self, name, fabric=True):
        path = self.folder / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("a.txt", b"unchanged")
            if fabric:
                archive.writestr("fabric.mod.json", b'{"id":"gui_test","version":"1.0","schemaVersion":1}')
        return path

    def test_minimum_window_keeps_actions_log_and_footer_visible(self):
        self.root.geometry("730x610")
        self.root.deiconify()
        self.root.update()
        for widget in (self.app.start_button, self.app.file_list, self.app.log_box, self.app.footer):
            self.assertTrue(widget.winfo_ismapped())
            self.assertGreater(widget.winfo_height(), 10)
            self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), self.root.winfo_rooty()+self.root.winfo_height())

    def test_buttons_select_multiple_files_and_folder(self):
        first = self.fixture("one.jar")
        second = self.fixture("two.jar")
        with patch("app.filedialog.askopenfilenames", return_value=(str(first), str(second))):
            self.app.choose_files()
        with patch("app.filedialog.askdirectory", return_value=str(self.folder)):
            self.app.choose_folder()
        self.assertEqual(len(self.app.paths), 2)
        self.assertEqual(self.app.file_list.size(), 2)
        self.assertEqual(str(self.app.start_button["state"]), "normal")

    def test_background_conversion_updates_progress_log_and_summary(self):
        self.app.add_paths([self.fixture("normal.jar"), self.fixture("plain.jar", False)])
        with patch("app.messagebox.showinfo") as popup:
            self.app.start()
            deadline = time.monotonic() + 15
            while self.app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertFalse(self.app.busy, "GUI worker did not finish")
            self.assertEqual(len(self.app.results), 2)
            self.assertEqual(int(self.app.progress["value"]), 2)
            self.assertIn("非 Fabric 模组", self.app.log_box.get("1.0", "end"))
            self.assertIn("成功 1 个", popup.call_args.args[1])
            self.assertIn("跳过 1 个", popup.call_args.args[1])
            self.assertEqual(str(self.app.files_button["state"]), "normal")

    def test_actual_windows_drop_message_with_multiple_chinese_paths(self):
        first = self.fixture("中文 模组一.jar")
        second = self.fixture("中文 模组二.jar")
        self.assertIsNotNone(self.app.drop, "Native Windows drop handler not installed")
        class DROPFILES(ctypes.Structure):
            _fields_ = [
                ("pFiles", wintypes.DWORD), ("pt", wintypes.POINT),
                ("fNC", wintypes.BOOL), ("fWide", wintypes.BOOL),
            ]
        data = (str(first) + "\0" + str(second) + "\0\0").encode("utf-16-le")
        header = DROPFILES(ctypes.sizeof(DROPFILES), wintypes.POINT(0, 0), False, True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        handle = kernel32.GlobalAlloc(0x0042, ctypes.sizeof(header) + len(data))
        self.assertTrue(handle)
        pointer = kernel32.GlobalLock(handle)
        self.assertTrue(pointer)
        ctypes.memmove(pointer, ctypes.byref(header), ctypes.sizeof(header))
        ctypes.memmove(pointer + ctypes.sizeof(header), data, len(data))
        kernel32.GlobalUnlock(handle)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        # The drop handler owns HDROP and frees it through DragFinish.
        user32.SendMessageW(self.app.drop.hwnd, 0x0233, handle, 0)
        self.assertEqual(self.app.paths, [first, second])

    def test_clear_queue_and_ignore_drop_during_conversion(self):
        self.app.add_paths([self.fixture("one.jar")])
        self.app.busy = True
        self.app.add_paths([self.fixture("two.jar")])
        self.assertEqual(len(self.app.paths), 1)
        self.app.busy = False
        self.app.clear()
        self.assertEqual(self.app.paths, [])
        self.assertEqual(str(self.app.start_button["state"]), "disabled")
