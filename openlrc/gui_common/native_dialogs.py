from __future__ import annotations

import ctypes
import os
import queue
import threading
from pathlib import Path
from uuid import UUID


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> GUID:
        raw = UUID(value).bytes_le
        data4 = (ctypes.c_ubyte * 8).from_buffer_copy(raw[8:])
        return cls(
            int.from_bytes(raw[0:4], "little"),
            int.from_bytes(raw[4:6], "little"),
            int.from_bytes(raw[6:8], "little"),
            data4,
        )


CLSID_FILE_OPEN_DIALOG = GUID.from_string("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
IID_I_FILE_OPEN_DIALOG = GUID.from_string("D57C7288-D4AD-4768-BE02-9D969532D960")
IID_I_SHELL_ITEM = GUID.from_string("43826D1E-E718-42EE-BC55-A1E261C37BFE")

CLSCTX_INPROC_SERVER = 0x1
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = 0x80010106
HRESULT_CANCELLED = 0x800704C7

FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_NOCHANGEDIR = 0x8
FOS_PATHMUSTEXIST = 0x800
SIGDN_FILESYSPATH = 0x80058000


def _normalize_initial_dir(initial_dir: str = "") -> Path:
    initial_path = Path(initial_dir).expanduser() if initial_dir else Path.home()
    if not initial_path.exists() or not initial_path.is_dir():
        return Path.home()
    return initial_path


def _hresult_code(value: int) -> int:
    return value & 0xFFFFFFFF


def _is_failed(value: int) -> bool:
    return _hresult_code(value) & 0x80000000 != 0


def _raise_for_hresult(value: int, message: str) -> None:
    if _is_failed(value):
        raise OSError(f"{message}: HRESULT 0x{_hresult_code(value):08X}")


def _release_com_object(obj: ctypes.c_void_p | None) -> None:
    if not obj or not obj.value:
        return
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    release(obj)


def _call_com_method(obj: ctypes.c_void_p, index: int, restype, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])


def _with_thread_dpi_awareness():
    user32 = ctypes.windll.user32
    set_context = getattr(user32, "SetThreadDpiAwarenessContext", None)
    if not set_context:
        return None
    set_context.argtypes = [ctypes.c_void_p]
    set_context.restype = ctypes.c_void_p
    try:
        return set_context(ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    except Exception:
        return None


def _restore_thread_dpi_awareness(previous_context) -> None:
    if not previous_context:
        return
    set_context = getattr(ctypes.windll.user32, "SetThreadDpiAwarenessContext", None)
    if not set_context:
        return
    try:
        set_context(previous_context)
    except Exception:
        pass


def _get_foreground_owner_hwnd() -> ctypes.c_void_p | None:
    user32 = ctypes.windll.user32
    get_foreground_window = getattr(user32, "GetForegroundWindow", None)
    is_window = getattr(user32, "IsWindow", None)
    if not get_foreground_window or not is_window:
        return None

    get_foreground_window.argtypes = []
    get_foreground_window.restype = ctypes.c_void_p
    is_window.argtypes = [ctypes.c_void_p]
    is_window.restype = ctypes.c_bool

    hwnd = get_foreground_window()
    if not hwnd:
        return None
    hwnd_pointer = ctypes.c_void_p(hwnd)
    if not is_window(hwnd_pointer):
        return None
    return hwnd_pointer


def _shell_item_from_path(path: Path) -> ctypes.c_void_p:
    shell_item = ctypes.c_void_p()
    shell32 = ctypes.windll.shell32
    shell32.SHCreateItemFromParsingName.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_void_p,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
    result = shell32.SHCreateItemFromParsingName(str(path), None, ctypes.byref(IID_I_SHELL_ITEM), ctypes.byref(shell_item))
    _raise_for_hresult(result, "创建初始目录 ShellItem 失败")
    return shell_item


def _choose_folder_native_windows(
    initial_dir: str = "",
    *,
    title: str = "选择 OpenLRC 扫描根目录",
    ok_label: str = "选择此文件夹",
) -> dict:
    initial_path = _normalize_initial_dir(initial_dir)
    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None

    dpi_context = _with_thread_dpi_awareness()
    initialized = False
    dialog = ctypes.c_void_p()
    folder_item = ctypes.c_void_p()
    result_item = ctypes.c_void_p()
    selected_path_ptr = ctypes.c_wchar_p()

    try:
        result = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
        result_code = _hresult_code(result)
        if result_code == RPC_E_CHANGED_MODE:
            raise RuntimeError("当前线程已用非 STA 模式初始化 COM，无法打开 Windows 原生文件夹选择器。")
        _raise_for_hresult(result, "初始化 COM 失败")
        initialized = True

        result = ole32.CoCreateInstance(
            ctypes.byref(CLSID_FILE_OPEN_DIALOG),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(IID_I_FILE_OPEN_DIALOG),
            ctypes.byref(dialog),
        )
        _raise_for_hresult(result, "创建 Windows 原生文件夹选择器失败")

        get_options = _call_com_method(dialog, 10, ctypes.c_long, ctypes.POINTER(ctypes.c_ulong))
        set_options = _call_com_method(dialog, 9, ctypes.c_long, ctypes.c_ulong)
        set_folder = _call_com_method(dialog, 12, ctypes.c_long, ctypes.c_void_p)
        set_title = _call_com_method(dialog, 17, ctypes.c_long, ctypes.c_wchar_p)
        set_ok_label = _call_com_method(dialog, 18, ctypes.c_long, ctypes.c_wchar_p)
        show = _call_com_method(dialog, 3, ctypes.c_long, ctypes.c_void_p)
        get_result = _call_com_method(dialog, 20, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))

        options = ctypes.c_ulong()
        _raise_for_hresult(get_options(dialog, ctypes.byref(options)), "读取文件夹选择器选项失败")
        options.value |= FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR
        _raise_for_hresult(set_options(dialog, options), "设置文件夹选择器选项失败")
        _raise_for_hresult(set_title(dialog, title), "设置文件夹选择器标题失败")
        _raise_for_hresult(set_ok_label(dialog, ok_label), "设置文件夹选择器确认按钮失败")

        try:
            folder_item = _shell_item_from_path(initial_path)
            _raise_for_hresult(set_folder(dialog, folder_item), "设置初始目录失败")
        finally:
            _release_com_object(folder_item)
            folder_item = ctypes.c_void_p()

        result = show(dialog, _get_foreground_owner_hwnd())
        if _hresult_code(result) == HRESULT_CANCELLED:
            return {"selected": False, "path": ""}
        _raise_for_hresult(result, "打开 Windows 原生文件夹选择器失败")

        _raise_for_hresult(get_result(dialog, ctypes.byref(result_item)), "获取选择结果失败")
        get_display_name = _call_com_method(result_item, 5, ctypes.c_long, ctypes.c_ulong, ctypes.POINTER(ctypes.c_wchar_p))
        _raise_for_hresult(
            get_display_name(result_item, SIGDN_FILESYSPATH, ctypes.byref(selected_path_ptr)),
            "读取选择目录路径失败",
        )

        selected = str(selected_path_ptr.value or "").strip()
        if not selected:
            return {"selected": False, "path": ""}
        return {"selected": True, "path": str(Path(selected).expanduser().resolve())}
    finally:
        if selected_path_ptr:
            ole32.CoTaskMemFree(selected_path_ptr)
        _release_com_object(result_item)
        _release_com_object(folder_item)
        _release_com_object(dialog)
        if initialized:
            ole32.CoUninitialize()
        _restore_thread_dpi_awareness(dpi_context)


def _choose_folder_tkinter(
    initial_dir: str = "",
    *,
    title: str = "选择 OpenLRC 扫描根目录",
) -> dict:
    initial_path = _normalize_initial_dir(initial_dir)

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError("当前 Python 环境无法打开本机文件夹选择器。") from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            parent=root,
            initialdir=str(initial_path),
            title=title,
            mustexist=True,
        )
    finally:
        root.destroy()

    selected = str(selected or "").strip()
    if not selected:
        return {"selected": False, "path": ""}
    return {"selected": True, "path": str(Path(selected).expanduser().resolve())}


def _choose_folder_native_windows_in_sta_thread(
    initial_dir: str = "",
    *,
    title: str,
    ok_label: str,
) -> dict:
    result_queue: queue.Queue[tuple[bool, dict | BaseException]] = queue.Queue(maxsize=1)

    def run_dialog() -> None:
        try:
            result_queue.put((True, _choose_folder_native_windows(initial_dir, title=title, ok_label=ok_label)))
        except BaseException as exc:
            result_queue.put((False, exc))

    thread = threading.Thread(target=run_dialog, name="WindowsNativeFolderDialog", daemon=True)
    thread.start()
    thread.join()

    if result_queue.empty():
        raise RuntimeError("Windows 原生文件夹选择器未返回结果。")

    ok, payload = result_queue.get()
    if ok:
        return dict(payload)
    raise payload


def choose_folder(
    initial_dir: str = "",
    *,
    title: str = "选择 OpenLRC 扫描根目录",
    ok_label: str = "选择此文件夹",
) -> dict:
    if os.name == "nt":
        return _choose_folder_native_windows_in_sta_thread(initial_dir, title=title, ok_label=ok_label)
    return _choose_folder_tkinter(initial_dir, title=title)
