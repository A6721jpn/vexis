import os
import sys # Added for frozen check
import glob
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QDockWidget, QListWidget, QListWidgetItem, QStackedWidget, 
                             QPushButton, QLabel, QProgressBar, QStatusBar,
                             QToolBar, QApplication, QMessageBox)
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction, QIcon, QPixmap

from src.gui.models.job_item import JobItem, JobStatus
from src.gui.file_watcher import InputFolderWatcher
from src.gui.job_manager import JobManager
from src.gui.panels.mesh_preview import MeshPreview
from src.gui.panels.progress_panel import ProgressPanel
from src.gui.panels.progress_panel import ProgressPanel
from src.gui.panels.progress_panel import ProgressPanel
from src.gui.panels.result_viewer import ResultViewer
from src.gui.about_dialog import AboutDialog
import src.version as v

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VEXIS-CAE - Automatic Rubberdome Analyzer")
        self.resize(1100, 700)
        
        # Stylesheet is now loaded globally via src/gui/styles/dark_theme.qss
        
        import sys
        
        # Paths
        if getattr(sys, 'frozen', False):
            # Running as compiled EXE
            root_dir = os.path.dirname(sys.executable)
        else:
            # Running as Python script
            base_dir = os.path.dirname(os.path.abspath(__file__)) # this is src/gui
            root_dir = os.path.dirname(os.path.dirname(base_dir)) # this is root
        
        # Set window icon (Delegated to QApplication in gui_main.py)
        # icon_path = os.path.join(root_dir, "icon.ico")
        # if os.path.exists(icon_path):
        #     self.setWindowIcon(QIcon(icon_path))
        
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
        outer_layout = QVBoxLayout(central_widget)
        
        # Top: Batch Progress Bar
        batch_frame = QWidget()
        batch_layout = QHBoxLayout(batch_frame)
        batch_layout.setContentsMargins(10, 5, 10, 5)
        
        self.batch_label = QLabel("Batch Progress:")
        self.batch_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        batch_layout.addWidget(self.batch_label)
        
        self.batch_progress = QProgressBar()
        self.batch_progress.setRange(0, 100)
        self.batch_progress.setValue(0)
        self.batch_progress.setMinimumHeight(25)
        self.batch_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 5px;
                text-align: center;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 4px;
            }
        """)
        batch_layout.addWidget(self.batch_progress, 1)
        
        self.batch_status = QLabel("0 / 0 completed")
        self.batch_status.setStyleSheet("font-size: 12px; margin-left: 10px;")
        batch_layout.addWidget(self.batch_status)
        
        outer_layout.addWidget(batch_frame)
        
        # Main content area
        main_layout = QHBoxLayout()
        
        # Left Panel: Job List
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(250)
        
        left_layout.addWidget(QLabel("Jobs"))
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
        
        outer_layout.addLayout(main_layout, 1)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _setup_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        
        # Helper to load icon (custom .ico or Qt standard fallback)
        # Helper to load icon (custom .ico/.svg or Qt standard fallback)
        def load_icon(name, fallback_standard):
            if getattr(sys, "frozen", False):
                # Frozen: Resources are copied to 'src/icons' next to the executable
                # build.py copies 'src/icons' to dist/VEXIS-CAE/src/icons
                icon_dir = os.path.join(os.path.dirname(sys.executable), "src", "icons")
            else:
                # Dev: src/gui/main_window.py -> src/ -> src/icons
                icon_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
            
            # Priority 1: SVG (Vector) - Dynamic Recoloring
            svg_path = os.path.join(icon_dir, f"{name}.svg")
            if os.path.exists(svg_path):
                try:
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_content = f.read()
                    
                    def create_pixmap_variant(content, color):
                        recolored = content.replace('"#000000"', f'"{color}"') \
                                           .replace('"black"', f'"{color}"') \
                                           .replace("'#000000'", f"'{color}'") \
                                           .replace("'black'", f"'{color}'")
                        data = bytearray(recolored, encoding='utf-8')
                        pm = QPixmap()
                        pm.loadFromData(data, "SVG")
                        return pm

                    # Normal State: Theme White
                    normal_pixmap = create_pixmap_variant(svg_content, "#EAF2FF")
                    
                    # Disabled State: Darker Gray (for low contrast against dark BG)
                    disabled_pixmap = create_pixmap_variant(svg_content, "#353D4A")

                    if not normal_pixmap.isNull():
                        icon = QIcon()
                        icon.addPixmap(normal_pixmap, QIcon.Normal)
                        icon.addPixmap(disabled_pixmap, QIcon.Disabled)
                        return icon
                except Exception as e:
                    print(f"SVG load error for {name}: {e}")

            # Priority 2: ICO (Legacy)
            ico_path = os.path.join(icon_dir, f"{name}.ico")
            if os.path.exists(ico_path):
                return QIcon(ico_path)
            
            return self.style().standardIcon(fallback_standard)
        
        from PySide6.QtWidgets import QStyle
        
        self.run_action = QAction(load_icon("start", QStyle.SP_MediaPlay), "Start Batch", self)
        self.run_action.triggered.connect(self.on_start_clicked)
        toolbar.addAction(self.run_action)
        
        # Note: using 'pause' SVG for Stop action if 'stop.svg' is missing, or fallback to standard
        self.stop_action = QAction(load_icon("pause", QStyle.SP_MediaStop), "Stop", self)
        self.stop_action.setEnabled(False)
        self.stop_action.triggered.connect(self.on_stop_clicked)
        toolbar.addAction(self.stop_action)
        
        self.skip_action = QAction(load_icon("skip", QStyle.SP_MediaSkipForward), "Skip", self)
        self.skip_action.setEnabled(False)
        self.skip_action.triggered.connect(self.on_skip_clicked)
        toolbar.addAction(self.skip_action)
        
        toolbar.addSeparator()
        
        self.refresh_action = QAction(load_icon("refresh-circle", QStyle.SP_BrowserReload), "Refresh", self)
        self.refresh_action.triggered.connect(self.on_refresh_clicked)
        toolbar.addAction(self.refresh_action)
        
        toolbar.addSeparator()
        
        # Config file buttons
        self.edit_config_action = QAction(load_icon("settings", QStyle.SP_FileDialogDetailedView), "Config", self)
        self.edit_config_action.setToolTip("Edit analysis/mesh config (config.yaml)")
        self.edit_config_action.triggered.connect(self.on_edit_config_clicked)
        toolbar.addAction(self.edit_config_action)
        
        self.edit_material_action = QAction(load_icon("material", QStyle.SP_FileDialogInfoView), "Material", self)
        self.edit_material_action.setToolTip("Edit material properties (material.yaml)")
        self.edit_material_action.triggered.connect(self.on_edit_material_clicked)
        toolbar.addAction(self.edit_material_action)
        
        
        toolbar.addSeparator()
        
        self.about_action = QAction(load_icon("about", QStyle.SP_MessageBoxInformation), "About", self)
        self.about_action.triggered.connect(self.on_about_clicked)
        toolbar.addAction(self.about_action)

        self.exit_action = QAction(load_icon("shutdown", QStyle.SP_DialogCloseButton), "Exit", self)
        self.exit_action.triggered.connect(self.on_exit_clicked)
        toolbar.addAction(self.exit_action)

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
        
        # Update batch progress
        self._update_batch_progress()

        if status == JobStatus.ERROR:
            job = self.jobs[job_id]
            err_msg = getattr(job, 'error_message', 'Unknown Error')
            QMessageBox.critical(self, "Analysis Error", f"Job '{job.name}' Failed.\n\nError: {err_msg}")
        elif status == JobStatus.STOPPED:
            job = self.jobs[job_id]
            QMessageBox.information(self, "Analysis Stopped", f"Job '{job.name}' was stopped by user.")
        
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
        if self._get_current_job_id() == job_id: # Corrected from 'current_job_id' to 'self._get_current_job_id()'
             self.progress_panel.append_log(line)

    @Slot()
    def on_about_clicked(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def _update_batch_progress(self):
        total = len(self.jobs)
        if total == 0:
            self.batch_progress.setValue(0)
            self.batch_status.setText("0 / 0 completed")
            return
        
        completed = sum(1 for j in self.jobs.values() 
                       if j.status in [JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.SKIPPED])
        percent = int((completed / total) * 100)
        self.batch_progress.setValue(percent)
        self.batch_status.setText(f"{completed} / {total} completed")

    def _refresh_list_ui(self):
        self.job_list_widget.clear()
        for job in self.jobs.values():
            list_item = QListWidgetItem(f"{job.name} [{job.display_status()}]")
            list_item.setData(Qt.UserRole, job.id)
            self.job_list_widget.addItem(list_item)
        self._update_batch_progress()

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
            self.result_panel.load_result(job.name, self.result_dir, self.temp_dir)
            
        elif job.status == JobStatus.RUNNING:
            self.preview_stack.setCurrentWidget(self.progress_panel)
            self.progress_panel.set_job_info(job.name, job.status_text, job.progress)
            
        else:
            self.preview_stack.setCurrentWidget(self.mesh_panel)
            # Always load STEP for pre-analysis/pending jobs
            self.mesh_panel.load_step(job.step_path)

    def on_start_clicked(self):
        self.run_action.setEnabled(False)
        self.stop_action.setEnabled(True)
        self.skip_action.setEnabled(True)
        self.job_manager.start_batch()

    def on_stop_clicked(self):
        self.run_action.setEnabled(True)
        self.stop_action.setEnabled(False)
        self.skip_action.setEnabled(False)
        self.job_manager.stop_batch()

    def on_skip_clicked(self):
        self.job_manager.skip_current_job()

    def on_refresh_clicked(self):
        self._init_existing_jobs()

    def on_edit_config_clicked(self):
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "config", "config.yaml")
        self._open_in_editor(config_path)

    def on_edit_material_clicked(self):
        material_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "config", "material.yaml")
        self._open_in_editor(material_path)

    def _open_in_editor(self, file_path):
        import subprocess
        if os.path.exists(file_path):
            # Windows: use notepad
            subprocess.Popen(["notepad.exe", file_path])
        else:
            QMessageBox.warning(self, "File Not Found", f"Config file not found:\n{file_path}")

    def on_exit_clicked(self):
        self.close()

    def closeEvent(self, event):
        # Show confirmation dialog
        reply = QMessageBox.question(
            self, 
            "Exit Confirmation",
            "Are you sure you want to exit?\nAll running analyses will be stopped.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # Stop all background processes
            self.status_bar.showMessage("Shutting down...")
            
            # Stop file watcher
            try:
                self.file_watcher.stop()
            except:
                pass
            
            # Stop batch processing and worker threads
            try:
                self.job_manager.stop_batch()
                if self.job_manager.worker and self.job_manager.worker.isRunning():
                    self.job_manager.worker.terminate()
                    self.job_manager.worker.wait(2000)
            except:
                pass
            
            # Clean up pyvista plotters
            try:
                if hasattr(self.mesh_panel, 'plotter') and self.mesh_panel.plotter:
                    self.mesh_panel.plotter.close()
                if hasattr(self.result_panel, 'plotter') and self.result_panel.plotter:
                    self.result_panel.plotter.close()
            except:
                pass
            
            event.accept()
        else:
            event.ignore()
