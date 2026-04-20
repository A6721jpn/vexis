import os
import glob
from PySide6.QtCore import QObject, QTimer, Signal
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class _StepFileHandler(FileSystemEventHandler):
    def __init__(self, callback_changed):
        self.callback_changed = callback_changed

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(
            (".stp", ".step")
        ):
            self.callback_changed()

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.lower().endswith(
            (".stp", ".step")
        ):
            self.callback_changed()

    def on_moved(self, event):
        if event.src_path.lower().endswith(
            (".stp", ".step")
        ) or event.dest_path.lower().endswith((".stp", ".step")):
            self.callback_changed()


class InputFolderWatcher(QObject):
    files_changed = Signal(list)
    _sync_requested = Signal()

    def __init__(self, input_dir):
        super().__init__()
        self.input_dir = os.path.abspath(input_dir)
        self.observer = Observer()
        self.handler = _StepFileHandler(self._on_changed)
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(350)
        self._rescan_timer.timeout.connect(self._emit_current_files)
        self._sync_requested.connect(self._schedule_rescan)

    def start(self):
        if not os.path.exists(self.input_dir):
            os.makedirs(self.input_dir)
        self.observer.schedule(self.handler, self.input_dir, recursive=False)
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()

    def get_existing_files(self):
        files = glob.glob(os.path.join(self.input_dir, "*.stp")) + glob.glob(
            os.path.join(self.input_dir, "*.step")
        )
        return [os.path.abspath(f) for f in files]

    def request_sync(self):
        self._sync_requested.emit()

    def _on_changed(self):
        self._sync_requested.emit()

    def _schedule_rescan(self):
        self._rescan_timer.start()

    def _emit_current_files(self):
        self.files_changed.emit(self.get_existing_files())
