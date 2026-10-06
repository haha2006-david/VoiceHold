"""System-wide push-to-talk dictation for Windows.

Hold the configured mouse button. Chinese speech is transcribed locally in
streaming mode and continuously inserted into the editable control that keeps
keyboard focus.
"""

from __future__ import annotations

import argparse
import ctypes as ct
from ctypes import wintypes
from dataclasses import asdict, dataclass, fields
import json
import logging
from pathlib import Path
import queue
import signal
import sys
import tarfile
import threading
import time
from typing import Any, Callable
from urllib.request import urlopen

import numpy as np
from opencc import OpenCC
import pyperclip
import sounddevice as sd
import sherpa_onnx

from core import HoldToTalk, ReleaseResult


# A PyInstaller one-file binary unpacks modules to a temporary directory.  Its
# editable configuration should live beside the executable instead.
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = APP_DIR / "voice_config.json"
EXAMPLE_CONFIG_PATH = APP_DIR / "voice_config.example.json"
STREAMING_MODEL_NAME = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
STREAMING_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{STREAMING_MODEL_NAME}.tar.bz2"
)
ACCURATE_MODEL_NAME = "sherpa-onnx-streaming-zipformer-zh-xlarge-int8-2025-06-30"
ACCURATE_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{ACCURATE_MODEL_NAME}.tar.bz2"
)
MODEL_DOWNLOAD_URLS = {
    STREAMING_MODEL_NAME: STREAMING_MODEL_URL,
    ACCURATE_MODEL_NAME: ACCURATE_MODEL_URL,
}


@dataclass(frozen=True)
class Config:
    trigger_button: str = "right"
    hold_to_record_ms: int = 350
    sample_rate: int = 16_000
    model: str = "base"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "zh"
    output_chinese: str = "simplified"
    streaming_model_dir: str = f"models/{STREAMING_MODEL_NAME}"
    recognizer_threads: int = 2
    render_interval_ms: int = 180
    vad_filter: bool = True
    restore_clipboard: bool = True

    def validate(self) -> None:
        if self.trigger_button not in {"left", "right"}:
            raise ValueError("trigger_button 必须是 left 或 right")
        if not 100 <= self.hold_to_record_ms <= 5_000:
            raise ValueError("hold_to_record_ms 必须在 100 到 5000 之间")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate 必须是正数")
        if self.output_chinese not in {"simplified", "original"}:
            raise ValueError("output_chinese 必须是 simplified 或 original")
        if self.recognizer_threads < 1:
            raise ValueError("recognizer_threads 必须至少为 1")
        if not 50 <= self.render_interval_ms <= 1_000:
            raise ValueError("render_interval_ms 必须在 50 到 1000 之间")


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(
            f"找不到配置文件：{path}\n"
            f"请先复制 {EXAMPLE_CONFIG_PATH.name} 为 {path.name}，再按需要修改。"
        )
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    allowed = {field.name for field in fields(Config)}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"配置中有未知字段：{', '.join(sorted(unknown))}")
    config = Config(**raw)
    config.validate()
    return config


class AudioRecorder:
    def __init__(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate
        self._chunks: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

    def start(self, on_audio: Callable[[np.ndarray], None] | None = None) -> None:
        if self._stream is not None:
            raise RuntimeError("录音已经开始")
        with self._lock:
            self._chunks = []

        def callback(indata: np.ndarray, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
            if status:
                logging.warning("麦克风状态：%s", status)
            samples = indata.copy().reshape(-1)
            with self._lock:
                self._chunks.append(samples)
            if on_audio is not None:
                on_audio(samples)

        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        if self._stream is None:
            raise RuntimeError("录音尚未开始")
        stream, self._stream = self._stream, None
        stream.stop()
        stream.close()
        return self.snapshot()

    def snapshot(self) -> np.ndarray:
        """Return a safe copy of all audio recorded so far for live preview."""
        with self._lock:
            if not self._chunks:
                return np.empty(0, dtype=np.float32)
            return np.concatenate(self._chunks, axis=0).reshape(-1)


class LiveTextInjector:
    """Replaces only the in-progress transcript inside the original input box."""

    def __init__(self, restore_clipboard: bool) -> None:
        self._restore_clipboard = restore_clipboard
        self._lock = threading.Lock()
        self._target_window = 0
        self._session = 0
        self._previous_text = ""
        self._clipboard_before: str | None = None
        self._last_clipboard_text = ""

    def begin(self, session: int, target_window: int) -> None:
        with self._lock:
            self._session = session
            self._target_window = target_window
            self._previous_text = ""
            self._last_clipboard_text = ""
            try:
                self._clipboard_before = pyperclip.paste()
            except pyperclip.PyperclipException:
                self._clipboard_before = None

    def replace(self, session: int, text: str) -> bool:
        with self._lock:
            if session != self._session:
                return False
            if not self._target_window or text == self._previous_text:
                return bool(self._target_window)
            foreground = int(user32.GetForegroundWindow() or 0)
            if foreground != self._target_window:
                # The mouse hook can cause a short focus transition in some
                # Chromium/WinUI inputs. Restore the field we captured on hold.
                user32.SetForegroundWindow(wintypes.HWND(self._target_window))
                time.sleep(0.03)
                foreground = int(user32.GetForegroundWindow() or 0)
                if foreground != self._target_window:
                    print("⚠ 未能回到原输入框，已跳过本次实时更新。", flush=True)
                    return False
            prefix_length = _common_prefix_length(self._previous_text, text)
            old_tail = self._previous_text[prefix_length:]
            new_tail = text[prefix_length:]
            # Keep the stable prefix in place. Only the uncertain tail changes,
            # so the input no longer flickers as each partial result arrives.
            for _ in old_tail:
                _send_virtual_key(VK_BACK)
            if new_tail:
                if not _send_unicode_text(new_tail):
                    pyperclip.copy(new_tail)
                    _send_paste_shortcut()
                    self._last_clipboard_text = new_tail
            self._previous_text = text
            return True

    def finish(self, session: int, final_text: str) -> None:
        self.replace(session, final_text)
        with self._lock:
            if session != self._session:
                return
            inserted, previous = self._last_clipboard_text, self._clipboard_before
            self._target_window = 0
            self._previous_text = ""
            self._clipboard_before = None
        if self._restore_clipboard and inserted and previous is not None:
            timer = threading.Timer(0.8, _restore_clipboard_if_unchanged, args=(inserted, previous))
            timer.daemon = True
            timer.start()


def _common_prefix_length(previous: str, current: str) -> int:
    """Length of immutable text shared by two successive ASR hypotheses."""
    limit = min(len(previous), len(current))
    index = 0
    while index < limit and previous[index] == current[index]:
        index += 1
    return index


class DictationService:
    """Feeds microphone chunks to a true streaming recognizer and live field."""

    def __init__(self, config: Config) -> None:
        self._config = config
        model_dir = resolve_streaming_model_dir(config)
        required = [model_dir / name for name in ("encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt")]
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "未找到实时识别模型。请先运行：\n"
                ".\\.venv\\Scripts\\python.exe voice_type.py --download-streaming-model"
            )
        print("正在载入实时中文识别模型…")
        self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(model_dir / "tokens.txt"),
            encoder=str(model_dir / "encoder.int8.onnx"),
            decoder=str(model_dir / "decoder.onnx"),
            joiner=str(model_dir / "joiner.int8.onnx"),
            num_threads=config.recognizer_threads,
            sample_rate=config.sample_rate,
            feature_dim=80,
            decoding_method="greedy_search",
        )
        self._converter = OpenCC("t2s") if config.output_chinese == "simplified" else None
        self._recorder = AudioRecorder(config.sample_rate)
        self._injector = LiveTextInjector(config.restore_clipboard)
        self._lock = threading.Lock()
        self._session = 0
        self._recording = False
        self._audio_queue: queue.Queue[np.ndarray | None] | None = None

    def start_recording(self, target_window: int) -> None:
        with self._lock:
            if self._recording:
                return
            self._session += 1
            session = self._session
            self._recording = True
            audio_queue: queue.Queue[np.ndarray | None] = queue.Queue()
            self._audio_queue = audio_queue

            def on_audio(samples: np.ndarray) -> None:
                audio_queue.put_nowait(samples)

            self._recorder.start(on_audio)
            self._injector.begin(session, target_window)
        threading.Thread(
            target=self._stream_audio,
            args=(session, target_window, audio_queue),
            name=f"streaming-asr-{session}",
            daemon=True,
        ).start()
        print("● 正在实时输入…", flush=True)

    def stop_recording(self) -> None:
        with self._lock:
            if not self._recording or self._audio_queue is None:
                return
            self._recording = False
            audio_queue = self._audio_queue
            self._recorder.stop()
            audio_queue.put(None)
        print("◌ 正在完成最后几个字…", flush=True)

    def _stream_audio(
        self,
        session: int,
        target_window: int,
        audio_queue: queue.Queue[np.ndarray | None],
    ) -> None:
        stream = self._recognizer.create_stream()
        last_text = ""
        last_rendered = ""
        last_render_time = 0.0
        minimum_render_interval = self._config.render_interval_ms / 1_000
        try:
            while True:
                samples = audio_queue.get()
                if samples is None:
                    # A short tail of silence lets the streaming decoder settle
                    # the last syllable before the user edits the result.
                    stream.accept_waveform(self._config.sample_rate, np.zeros(self._config.sample_rate // 3, dtype=np.float32))
                    self._decode_ready(stream)
                    text = self._normalize(self._recognizer.get_result(stream))
                    self._injector.finish(session, text or last_text)
                    print(f"✓ {text or last_text}", flush=True)
                    return
                stream.accept_waveform(self._config.sample_rate, samples)
                self._decode_ready(stream)
                text = self._normalize(self._recognizer.get_result(stream))
                if text:
                    last_text = text
                now = time.monotonic()
                if last_text != last_rendered and now - last_render_time >= minimum_render_interval:
                    if self._injector.replace(session, last_text):
                        last_rendered = last_text
                        last_render_time = now
        except Exception as error:
            logging.exception("实时转写失败")
            print(f"实时转写失败：{error}", flush=True)

    def _decode_ready(self, stream: Any) -> None:
        while self._recognizer.is_ready(stream):
            self._recognizer.decode_stream(stream)

    def _normalize(self, text: str) -> str:
        text = text.strip()
        return self._converter.convert(text) if self._converter is not None else text


def _send_paste_shortcut() -> None:
    """Paste the current clipboard without changing focus or the clipboard."""
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _restore_clipboard_if_unchanged(inserted: str, previous: str) -> None:
    try:
        if pyperclip.paste() == inserted:
            pyperclip.copy(previous)
    except pyperclip.PyperclipException:
        logging.warning("无法恢复剪贴板")


def resolve_streaming_model_dir(config: Config) -> Path:
    model_dir = Path(config.streaming_model_dir)
    return model_dir if model_dir.is_absolute() else APP_DIR / model_dir


def download_streaming_model(config: Config) -> int:
    """Download the model explicitly, keeping a partial archive for recovery."""
    model_dir = resolve_streaming_model_dir(config)
    model_name = model_dir.name
    try:
        model_url = MODEL_DOWNLOAD_URLS[model_name]
    except KeyError as error:
        raise ValueError(f"不支持自动下载的模型目录：{model_name}") from error
    required = [model_dir / name for name in ("encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt")]
    if all(path.is_file() for path in required):
        print(f"实时模型已存在：{model_dir}")
        return 0
    if model_dir.exists():
        raise RuntimeError(f"模型目录不完整，请检查后再重试：{model_dir}")
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    archive_path = model_dir.parent / f"{model_name}.tar.bz2"
    print(f"正在下载实时中文模型：{model_name}…")
    with urlopen(model_url) as response, archive_path.open("wb") as output:
        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            downloaded += len(chunk)
            if total:
                print(f"\r已下载 {downloaded / total:.0%}", end="", flush=True)
    print("\n正在解压模型…")
    extraction_root = model_dir.parent.resolve()
    with tarfile.open(archive_path, "r:bz2") as archive:
        for member in archive.getmembers():
            destination = (extraction_root / member.name).resolve()
            if extraction_root != destination and extraction_root not in destination.parents:
                raise RuntimeError("模型压缩包包含不安全的文件路径")
        archive.extractall(extraction_root, filter="data")
    archive_path.unlink()
    print(f"实时模型已准备好：{model_dir}")
    return 0


# Windows low-level mouse hook declarations.
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
LLMHF_INJECTED = 0x00000001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
VK_CONTROL = 0x11
VK_V = 0x56
VK_BACK = 0x08
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1
WM_QUIT = 0x0012
ERROR_ALREADY_EXISTS = 183
INSTANCE_MUTEX_NAME = "Local\\VoiceHold-GlobalDictation"

ULONG_PTR = wintypes.WPARAM


class POINT(ct.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSLLHOOKSTRUCT(ct.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ct.Structure):
    _fields_ = [
        ("wVk", ct.c_ushort),
        ("wScan", ct.c_ushort),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ct.Structure):
    # Included so INPUT has Windows' required 40-byte size on 64-bit systems.
    # SendInput rejects a smaller union even when every event is keyboard-only.
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ct.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ct.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUT_UNION)]


user32 = ct.WinDLL("user32", use_last_error=True)
kernel32 = ct.WinDLL("kernel32", use_last_error=True)
LowLevelMouseProc = ct.WINFUNCTYPE(ct.c_ssize_t, ct.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ct.c_int, LowLevelMouseProc, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ct.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = ct.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetMessageW.argtypes = [ct.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ct.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ct.POINTER(wintypes.MSG)]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SendInput.argtypes = [wintypes.UINT, ct.POINTER(INPUT), ct.c_int]
user32.SendInput.restype = wintypes.UINT
kernel32.CreateMutexW.argtypes = [ct.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


def _claim_single_instance() -> wintypes.HANDLE | None:
    """Return a process-held mutex, or None when VoiceHold already runs."""
    handle = kernel32.CreateMutexW(None, False, INSTANCE_MUTEX_NAME)
    if not handle:
        raise ct.WinError(ct.get_last_error())
    if ct.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return None
    return handle


def _send_virtual_key(key: int) -> None:
    user32.keybd_event(key, 0, 0, 0)
    user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)


def _send_unicode_text(text: str) -> bool:
    """Use Windows' Unicode keyboard events, without relying on Ctrl+V."""
    units = text.encode("utf-16-le")
    inputs = (INPUT * (len(units)))()
    for index in range(0, len(units), 2):
        code_unit = int.from_bytes(units[index : index + 2], "little")
        down = inputs[index]
        down.type = INPUT_KEYBOARD
        down.ki = KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE, 0, 0)
        up = inputs[index + 1]
        up.type = INPUT_KEYBOARD
        up.ki = KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)
    return bool(inputs) and user32.SendInput(len(inputs), inputs, ct.sizeof(INPUT)) == len(inputs)


class GlobalMouseHook:
    """Suppress the configured button and replay short clicks as ordinary clicks."""

    def __init__(self, config: Config, dictation: DictationService) -> None:
        if config.trigger_button == "left":
            self._down_message, self._up_message = WM_LBUTTONDOWN, WM_LBUTTONUP
            self._down_flag, self._up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        else:
            self._down_message, self._up_message = WM_RBUTTONDOWN, WM_RBUTTONUP
            self._down_flag, self._up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        self._dictation = dictation
        self._controller = HoldToTalk(config.hold_to_record_ms / 1_000, self._start_dictation, dictation.stop_recording)
        self._handle: wintypes.HHOOK | None = None
        self._thread_id: int | None = None
        self._callback = LowLevelMouseProc(self._mouse_proc)

    def run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        self._handle = user32.SetWindowsHookExW(
            # A low-level hook executes its callback in this process. Passing
            # Python's EXE as hmod makes Windows try to load it as a hook DLL
            # and fails with WinError 126.
            WH_MOUSE_LL, self._callback, None, 0
        )
        if not self._handle:
            raise ct.WinError(ct.get_last_error())
        print("已就绪：按住说话时，文字会直接出现在当前输入框。按 Ctrl+C 退出。", flush=True)
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ct.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ct.byref(message))
                user32.DispatchMessageW(ct.byref(message))
        finally:
            if self._handle:
                user32.UnhookWindowsHookEx(self._handle)
                self._handle = None

    def stop(self) -> None:
        if self._handle:
            user32.UnhookWindowsHookEx(self._handle)
            self._handle = None
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _mouse_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code != HC_ACTION:
            return user32.CallNextHookEx(self._handle, n_code, w_param, l_param)
        info = ct.cast(l_param, ct.POINTER(MSLLHOOKSTRUCT)).contents
        if info.flags & LLMHF_INJECTED:
            return user32.CallNextHookEx(self._handle, n_code, w_param, l_param)
        if w_param == self._down_message:
            self._controller.press()
            return 1
        if w_param == self._up_message:
            result = self._controller.release()
            if result == ReleaseResult.TAP:
                user32.mouse_event(self._down_flag, 0, 0, 0, 0)
                user32.mouse_event(self._up_flag, 0, 0, 0, 0)
            return 1
        return user32.CallNextHookEx(self._handle, n_code, w_param, l_param)

    def _start_dictation(self) -> None:
        # The original input keeps focus throughout the live transcription.
        target_window = int(user32.GetForegroundWindow() or 0)
        self._dictation.start_recording(target_window)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Windows 全局实时语音输入")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="配置 JSON 路径")
    parser.add_argument("--write-default-config", action="store_true", help="生成默认配置后退出")
    parser.add_argument("--download-streaming-model", action="store_true", help="下载实时中文模型后退出")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.write_default_config:
        if args.config.exists():
            print(f"配置已经存在，未覆盖：{args.config}")
            return 1
        args.config.write_text(json.dumps(asdict(Config()), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已创建：{args.config}")
        return 0
    instance_mutex: wintypes.HANDLE | None = None
    try:
        config = load_config(args.config)
        if args.download_streaming_model:
            return download_streaming_model(config)
        instance_mutex = _claim_single_instance()
        if instance_mutex is None:
            print("VoiceHold 已在运行。", flush=True)
            return 0
        dictation = DictationService(config)
        hook = GlobalMouseHook(config, dictation)
        signal.signal(signal.SIGINT, lambda _signum, _frame: hook.stop())
        hook.run()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f"启动失败：{error}", file=sys.stderr)
        return 1
    finally:
        if "hook" in locals():
            hook.stop()
        if instance_mutex:
            kernel32.CloseHandle(instance_mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
