import os
import glob
from PySide6.QtCore import QObject, Signal, QFileSystemWatcher
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class _StepFileHandler(FileSystemEventHandler):
    def __init__(self, callback_added, callback_removed):
        self.callback_added = callback_added
        self.callback_removed = callback_removed

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(('.stp', '.step')):
            self.callback_added(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.lower().endswith(('.stp', '.step')):
            self.callback_removed(event.src_path)

    def on_moved(self, event):
        # Handle rename as delete + add
        if event.src_path.lower().endswith(('.stp', '.step')):
            self.callback_removed(event.src_path)
        if event.dest_path.lower().endswith(('.stp', '.step')):
            self.callback_added(event.dest_path)

class InputFolderWatcher(QObject):
    file_added = Signal(str)
    file_removed = Signal(str)

    def __init__(self, input_dir):
        super().__init__()
        self.input_dir = os.path.abspath(input_dir)
        self.observer = Observer()
        self.handler = _StepFileHandler(self._on_added, self._on_removed)

    def start(self):
        if not os.path.exists(self.input_dir):
            os.makedirs(self.input_dir)
        self.observer.schedule(self.handler, self.input_dir, recursive=False)
        self.observer.start()

    def stop(self):
        self.observer.stop()
        self.observer.join()

    def get_existing_files(self):
        files = glob.glob(os.path.join(self.input_dir, "*.stp")) + \
                glob.glob(os.path.join(self.input_dir, "*.step"))
        return [os.path.abspath(f) for f in files]

    def _on_added(self, path):
        self.file_added.emit(os.path.abspath(path))

    def _on_removed(self, path):
        self.file_removed.emit(os.path.abspath(path))
