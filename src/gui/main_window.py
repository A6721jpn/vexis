import os
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QListWidget, QListWidgetItem, QStackedWidget, 
                             QPushButton, QLabel, QProgressBar, QStatusBar,
                             QToolBar, QApplication)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction, QIcon

from src.gui.models.job_item import JobItem, JobStatus
from src.gui.file_watcher import InputFolderWatcher
from src.gui.job_manager import JobManager
from src.gui.panels.mesh_preview import MeshPreview
from src.gui.panels.progress_panel import ProgressPanel
from src.gui.panels.result_viewer import ResultViewer

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VEXIS-CAE - Auto Analysis Workflow")
        self.resize(1100, 700)
        
        # Paths
        base_dir = os.path.dirname(os.path.abspath(__file__)) # this is src/gui
        root_dir = os.path.dirname(os.path.dirname(base_dir)) # this is root
        
        self.input_dir = os.path.join(root_dir, "input")
        self.temp_dir = os.path.join(root_dir, "temp")
        self.result_dir = os.path.join(root_dir, "results")
        self.config_path = os.path.join(root_dir, "config", "config.yaml")

        self.jobs = {} # id -> JobItem
        
        # Components
        self.job_manager = JobManager(self.input_dir, self.temp_dir, self.result_dir, self.config_path)
        self.file_watcher = InputFolderWatcher(self.input_dir)
        
        self._setup_ui()
        self._setup_toolbar()
        self._connect_signals()
        
        # Start watching
        self._init_existing_jobs()
        self.file_watcher.start()
        
    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Left Panel: Job List
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(250)
        
        left_layout.addWidget(QLabel("📁 Jobs"))
        self.job_list_widget = QListWidget()
        self.job_list_widget.currentRowChanged.connect(self.on_job_selected)
        left_layout.addWidget(self.job_list_widget)
        
        # Right Panel: Preview (Stacked)
        self.preview_stack = QStackedWidget()
        
        # Panel 1: Placeholder/Empty
        self.empty_panel = QLabel("Select a job to preview")
        self.empty_panel.setAlignment(Qt.AlignCenter)
        self.preview_stack.addWidget(self.empty_panel)
        
        # Panel 2: Mesh Preview
        self.mesh_panel = MeshPreview()
        self.preview_stack.addWidget(self.mesh_panel)
        
        # Panel 3: Progress/Log
        self.progress_panel = ProgressPanel()
        self.preview_stack.addWidget(self.progress_panel)
        
        # Panel 4: Result Viewer
        self.result_panel = ResultViewer()
        self.preview_stack.addWidget(self.result_panel)
        
        main_layout.addWidget(left_panel)
        main_layout.addWidget(self.preview_stack, 1)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)
        
        self.run_action = QAction("▶ Start Batch", self)
        self.run_action.triggered.connect(self.on_start_clicked)
        toolbar.addAction(self.run_action)
        
        self.stop_action = QAction("■ Stop", self)
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self.on_stop_clicked)
        toolbar.addAction(self.stop_action)
        
        toolbar.addSeparator()
        
        self.refresh_action = QAction("🔄 Refresh", self)
        self.refresh_action.triggered.connect(self.on_refresh_clicked)
        toolbar.addAction(self.refresh_action)

    def _connect_signals(self):
        self.file_watcher.file_added.connect(self.job_manager.add_job_from_path)
        self.file_watcher.file_removed.connect(self.job_manager.remove_job_by_path)
        
        self.job_manager.job_added.connect(self._on_job_added)
        self.job_manager.job_removed.connect(self._on_job_removed)
        self.job_manager.status_changed.connect(self._on_job_status_changed)
        self.job_manager.progress_changed.connect(self._on_job_progress_changed)
        self.job_manager.log_added.connect(self._on_job_log_added)

    def _init_existing_jobs(self):
        for path in self.file_watcher.get_existing_files():
            self.job_manager.add_job_from_path(path)

    @Slot(JobItem)
    def _on_job_added(self, job):
        self.jobs[job.id] = job
        list_item = QListWidgetItem(f"{job.name} [{job.display_status()}]")
        list_item.setData(Qt.UserRole, job.id)
        self.job_list_widget.addItem(list_item)

    @Slot(str)
    def _on_job_removed(self, job_id):
        if job_id in self.jobs:
            del self.jobs[job_id]
            self._refresh_list_ui()

    @Slot(str, JobStatus)
    def _on_job_status_changed(self, job_id, status):
        for i in range(self.job_list_widget.count()):
            item = self.job_list_widget.item(i)
            if item.data(Qt.UserRole) == job_id:
                job = self.jobs[job_id]
                item.setText(f"{job.name} [{job.display_status()}]")
                break
        
        current_job_id = self._get_current_job_id()
        if current_job_id == job_id:
            self.on_job_selected(self.job_list_widget.currentRow())

    @Slot(str, int, str)
    def _on_job_progress_changed(self, job_id, progress, status_text):
        if self._get_current_job_id() == job_id:
            job = self.jobs[job_id]
            self.progress_panel.set_job_info(job.name, status_text, progress)

    @Slot(str, str)
    def _on_job_log_added(self, job_id, line):
        if self._get_current_job_id() == job_id:
            self.progress_panel.append_log(line)

    def _refresh_list_ui(self):
        self.job_list_widget.clear()
        for job in self.jobs.values():
            list_item = QListWidgetItem(f"{job.name} [{job.display_status()}]")
            list_item.setData(Qt.UserRole, job.id)
            self.job_list_widget.addItem(list_item)

    def _get_current_job_id(self):
        row = self.job_list_widget.currentRow()
        if row < 0: return None
        return self.job_list_widget.item(row).data(Qt.UserRole)

    @Slot(int)
    def on_job_selected(self, index):
        if index < 0:
            self.preview_stack.setCurrentIndex(0)
            return
            
        item = self.job_list_widget.item(index)
        job_id = item.data(Qt.UserRole)
        job = self.jobs.get(job_id)
        
        if not job:
            self.preview_stack.setCurrentIndex(0)
            return
            
        if job.status == JobStatus.COMPLETED:
            self.preview_stack.setCurrentWidget(self.result_panel)
            res_base = os.path.join(self.result_dir, job.name)
            self.result_panel.load_result(res_base)
            
        elif job.status == JobStatus.RUNNING:
            self.preview_stack.setCurrentWidget(self.progress_panel)
            self.progress_panel.set_job_info(job.name, job.status_text, job.progress)
            
        else:
            self.preview_stack.setCurrentWidget(self.mesh_panel)
            vtk_path = os.path.join(self.temp_dir, f"{job.name}.vtk")
            self.mesh_panel.load_mesh(vtk_path)

    def on_start_clicked(self):
        self.run_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.job_manager.start_batch()

    def on_stop_clicked(self):
        self.run_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.job_manager.stop_batch()

    def on_refresh_clicked(self):
        self._init_existing_jobs()

    def closeEvent(self, event):
        self.file_watcher.stop()
        self.job_manager.stop_batch()
        event.accept()
