"""Native Windows Explorer drop support. No tkinterdnd2 or other dependency."""
from __future__ import annotations

import os


class WindowsDrop:
    def __init__(self, root, on_paths, on_error):
        if os.name != "nt":
            raise OSError("原生拖放仅支持 Windows；仍可使用选择文件/文件夹")
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        root.update_idletasks()
        self.user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user32.GetAncestor.restype = wintypes.HWND
        self.hwnd = self.user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()
        self.shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        self.shell32.DragAcceptFiles.restype = None
        self.shell32.DragQueryFileW.argtypes = [
            wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT
        ]
        self.shell32.DragQueryFileW.restype = wintypes.UINT
        self.shell32.DragFinish.argtypes = [wintypes.HANDLE]
        self.shell32.DragFinish.restype = None
        self.user32.CallWindowProcW.argtypes = [
            ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        self.user32.CallWindowProcW.restype = ctypes.c_ssize_t
        self._set_proc = (
            self.user32.SetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8
            else self.user32.SetWindowLongW
        )
        self._set_proc.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        self._set_proc.restype = ctypes.c_void_p
        proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        def window_proc(hwnd, message, wparam, lparam):
            if message == 0x0233:  # WM_DROPFILES
                try:
                    count = self.shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                    paths = []
                    for index in range(count):
                        size = self.shell32.DragQueryFileW(wparam, index, None, 0)
                        buffer = ctypes.create_unicode_buffer(size + 1)
                        self.shell32.DragQueryFileW(wparam, index, buffer, size + 1)
                        paths.append(buffer.value)
                    on_paths(paths)
                except Exception as exc:
                    on_error(f"拖放读取失败：{exc}")
                finally:
                    self.shell32.DragFinish(wparam)
                return 0
            return self.user32.CallWindowProcW(self._old_proc, hwnd, message, wparam, lparam)

        # Retain both callbacks until the original WNDPROC has been restored.
        self._callback = proc_type(window_proc)
        ctypes.set_last_error(0)
        self._old_proc = self._set_proc(
            self.hwnd, -4, ctypes.cast(self._callback, ctypes.c_void_p)
        )
        if not self._old_proc:
            raise ctypes.WinError(ctypes.get_last_error())
        self._active = True
        self.shell32.DragAcceptFiles(self.hwnd, True)

    def close(self):
        if self._active:
            self.shell32.DragAcceptFiles(self.hwnd, False)
            self._set_proc(self.hwnd, -4, self._old_proc)
            self._active = False
