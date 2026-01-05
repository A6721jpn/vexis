"""
Sleep Manager - Windows PCのスリープと画面OFFを防止するユーティリティ

Windows API SetThreadExecutionState を使用して、アプリケーション実行中の
システムスリープと画面オフを制御します。
"""
import ctypes
import sys

# Windows API Flags
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def prevent_sleep():
    """スリープと画面OFFを防止する
    
    この関数を呼び出すと、明示的に allow_sleep() を呼び出すまで
    PCはスリープ状態に入らず、画面もOFFになりません。
    """
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        )


def allow_sleep():
    """通常のスリープ動作に戻す
    
    prevent_sleep() で設定したスリープ防止を解除し、
    OSの電源設定に従った通常動作に戻します。
    """
    if sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
