import os
import sys
import re
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
from src.gui.panels.result_viewer import ResultViewer
from src.gui.about_dialog import AboutDialog
from src.utils.sleep_manager import prevent_sleep, allow_sleep
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
        
        # Start with no job selected (show logo placeholder)
        
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
        
        # Panel 1: Placeholder/Empty with logo
        self.empty_panel = QLabel()
        self.empty_panel.setAlignment(Qt.AlignCenter)
        self.empty_panel.setStyleSheet("background-color: #0B0F14;")
        
        # Load logo for placeholder
        import sys
        if getattr(sys, 'frozen', False):
            logo_root = os.path.dirname(sys.executable)
        else:
            logo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        logo_path = os.path.join(logo_root, "doc", "VEXIS-CAE-LOGO-LARGE.png")
        if os.path.exists(logo_path):
            logo_pix = QPixmap(logo_path).scaled(400, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.empty_panel.setPixmap(logo_pix)
        else:
            self.empty_panel.setText("Select a job to preview")
        
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
        
        # Import shared icon loader with caching
        from src.gui.utils import load_icon
        from PySide6.QtWidgets import QStyle
        
        # Define toolbar actions with (icon_name, fallback, label, handler, enabled)
        actions = [
            ("start", QStyle.SP_MediaPlay, "Start Batch", self.on_start_clicked, True),
            ("pause", QStyle.SP_MediaStop, "Stop", self.on_stop_clicked, False),
            ("skip", QStyle.SP_MediaSkipForward, "Skip", self.on_skip_clicked, False),
            None,  # Separator
            ("refresh-circle", QStyle.SP_BrowserReload, "Refresh", self.on_refresh_clicked, True),
            None,
            ("settings", QStyle.SP_FileDialogDetailedView, "Config", self.on_edit_config_clicked, True),
            ("material", QStyle.SP_FileDialogInfoView, "Material", self.on_edit_material_clicked, True),
            None,
            ("about", QStyle.SP_MessageBoxInformation, "About", self.on_about_clicked, True),
            ("shutdown", QStyle.SP_DialogCloseButton, "Exit", self.on_exit_clicked, True),
            None,
            None,  # Double separator for spacing
        ]
        
        # Create actions from definition
        self.run_action = self.stop_action = self.skip_action = None
        for item in actions:
            if item is None:
                toolbar.addSeparator()
            else:
                icon_name, fallback, label, handler, enabled = item
                action = QAction(load_icon(icon_name, fallback, self.style()), label, self)
                action.setEnabled(enabled)
                action.triggered.connect(handler)
                toolbar.addAction(action)
                
                # Store references for dynamic enable/disable
                if label == "Start Batch":
                    self.run_action = action
                elif label == "Stop":
                    self.stop_action = action
                elif label == "Skip":
                    self.skip_action = action
        
        # Sleep Prevention Toggle (Icon-based)
        self._sleep_enabled = False
        self._sleep_icon_on = load_icon("eye-solid", QStyle.SP_DialogApplyButton, self.style())
        self._sleep_icon_off = load_icon("eye-closed", QStyle.SP_DialogCancelButton, self.style())
        
        self.sleep_action = QAction(self._sleep_icon_off, "Keep Awake", self)
        self.sleep_action.setToolTip("Anti-sleep ON/OFF")
        self.sleep_action.triggered.connect(self._on_sleep_toggle_clicked)
        toolbar.addAction(self.sleep_action)


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
        self._refresh_list_ui()

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
        current_id = self._get_current_job_id()
        self.job_list_widget.blockSignals(True)
        self.job_list_widget.clear()
        
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower()
                    for text in re.split('([0-9]+)', s)]
        
        sorted_jobs = sorted(self.jobs.values(), key=lambda j: natural_sort_key(j.name))
        
        for job in sorted_jobs:
            list_item = QListWidgetItem(f"{job.name} [{job.display_status()}]")
            list_item.setData(Qt.UserRole, job.id)
            self.job_list_widget.addItem(list_item)
            
            if job.id == current_id:
                self.job_list_widget.setCurrentItem(list_item)
                
        self.job_list_widget.blockSignals(False)
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

        # Priority 1: PENDING jobs always show STEP preview
        if job.status == JobStatus.PENDING:
            self.preview_stack.setCurrentWidget(self.mesh_panel)
            self.mesh_panel.load_step(job.step_path)
            return
            
        # Priority 2: RUNNING jobs show progress/log panel
        if job.status == JobStatus.RUNNING:
            self.preview_stack.setCurrentWidget(self.progress_panel)
            self.progress_panel.set_job_info(job.name, job.status_text, job.progress)
            return

        # Priority 3: For COMPLETED/SKIPPED/STOPPED/ERROR - check if result file exists
        import os
        base = job.name
        possible_paths = [
            os.path.join(self.result_dir, f"{base}.xplt"),
            os.path.join(self.temp_dir, f"{base}.xplt"),
            os.path.join(os.getcwd(), "results", f"{base}.xplt"),
            os.path.join(os.getcwd(), "temp", f"{base}.xplt"),
        ]
        
        has_result = False
        if job.result_path and os.path.exists(job.result_path):
             has_result = True
        else:
            for p in possible_paths:
                if p and os.path.exists(p):
                    has_result = True
                    break
            
        if has_result:
            self.preview_stack.setCurrentWidget(self.result_panel)
            self.result_panel.load_result(job.name, self.result_dir, self.temp_dir)
        else:
            # No result file - show STEP as fallback
            self.preview_stack.setCurrentWidget(self.mesh_panel)
            self.mesh_panel.load_step(job.step_path)

    def on_start_clicked(self):
        # Validate filenames (ASCII check)
        invalid_jobs = self.job_manager.get_invalid_jobs()
        if invalid_jobs:
            names = "\n".join([f"・ {j.name}" for j in invalid_jobs])
            QMessageBox.warning(
                self, 
                "不正なファイル名", 
                f"以下のファイル名に日本語等の全角文字が含まれています：\n\n{names}\n\n"
                "解析を確実に実行するため、ファイル名を半角英数字（例: case_0）に変更してください。"
            )
            return

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

    def _on_sleep_toggle_clicked(self):
        """Callback for sleep prevention toggle button"""
        self._sleep_enabled = not self._sleep_enabled
        
        if self._sleep_enabled:
            prevent_sleep()
            self.sleep_action.setIcon(self._sleep_icon_on)
            self.status_bar.showMessage("Sleep prevention: ON - PC will stay awake")
        else:
            allow_sleep()
            self.sleep_action.setIcon(self._sleep_icon_off)
            self.status_bar.showMessage("Sleep prevention: OFF - Normal behavior")

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
            # Restore normal sleep behavior on exit
            allow_sleep()
            
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
