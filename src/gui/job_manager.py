import os
import glob
import re
import uuid
import time
import yaml
from PySide6.QtCore import QObject, QThread, Signal, Slot
from src.gui.models.job_item import JobItem, JobStatus
import analysis_helpers as helpers

class AnalysisWorker(QThread):
    progress_updated = Signal(str, int, str) # job_id, progress, status_text
    log_updated = Signal(str, str)           # job_id, log_line
    finished = Signal(str, bool, str)             # job_id, success, error_message

    def __init__(self, job: JobItem, config_path: str, temp_dir: str, result_dir: str):
        super().__init__()
        self.job = job
        self.config_path = config_path
        self.temp_dir = temp_dir
        self.result_dir = result_dir
        self._is_running = True
        self._stopped = False
        self._skipped = False

    def run(self):
        job_id = self.job.id
        base_name = self.job.name
        
        def log_cb(line):
            self.log_updated.emit(job_id, line)
            
        def prog_cb(percent):
            # Scale solver percentage (20-99%)
            val = 20 + int(percent * 0.79)
            self.progress_updated.emit(job_id, val, f"Solving ({percent}%)")

        try:
            # --- Load Config ---
            push_dist, sim_steps = -1.0, 20
            febio_path = None
            template_name = "template2.feb"
            
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    conf = yaml.safe_load(f).get("analysis", {})
                    push_dist = conf.get("push_dist", push_dist)
                    sim_steps = conf.get("time_steps", sim_steps)
                    febio_path = conf.get("febio_path", None)
                    template_name = conf.get("template_feb", template_name)

            # Resolve template path (relative to config dir usually, but here relative to root/base)
            # Assuming template is in the app root or specified path
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(self.config_path))) # vexis root
            template_path = os.path.join(base_dir, template_name)
            if not os.path.exists(template_path):
                # Fallback to internal default if not found
                template_path = helpers.DEFAULT_TEMPLATE

            # --- Initialize Log ---
            log_path = os.path.join(self.temp_dir, f"{base_name}.log")
            # Clear previous log
            with open(log_path, "w", encoding="utf-8") as f: 
                f.write(f"=== Analysis Log for {base_name} ===\n")

            # --- 1. Meshing ---
            self.progress_updated.emit(job_id, 1, "Meshing...")
            vtk_path = helpers.run_meshing(self.job.step_path, self.config_path, self.temp_dir, log_path=log_path, log_callback=log_cb)
            self.job.vtk_path = vtk_path
            self.progress_updated.emit(job_id, 5, "Mesh Complete")
            
            if not self._is_running: return

            # --- 2. Integration ---
            self.progress_updated.emit(job_id, 10, "Preparing FEBio model...")
            out_feb = os.path.join(self.temp_dir, f"{base_name}.feb")
            helpers.run_integration(vtk_path, template_path, out_feb, push_dist, sim_steps, log_path=log_path)
            self.job.feb_path = out_feb
            self.progress_updated.emit(job_id, 15, "Prep Complete")
            
            if not self._is_running: return

            # --- 3. Solver ---
            self.progress_updated.emit(job_id, 20, "Solving (0%)")
            
            # Callback to check if stopped/skipped from GUI thread
            def check_stop():
                return not self._is_running

            success = helpers.run_solver_and_extract(
                out_feb, self.result_dir, 
                log_path=log_path,
                febio_exe=febio_path,
                log_callback=log_cb, 
                progress_callback=prog_cb,
                check_stop_callback=check_stop
            )
            
            # If manually stopped or skipped, do NOT emit Success/Fail finished signal here.
            # It is handled by stop()/skip() method.
            if self._stopped or self._skipped:
                return

            if success:
                self.progress_updated.emit(job_id, 100, "Completed")
                self.finished.emit(job_id, True, "")
            else:
                self.progress_updated.emit(job_id, 100, "Error")
                self.finished.emit(job_id, False, "Solver failed (check log)")

        except Exception as e:
            msg = f"Worker Error: {str(e)}"
            self.log_updated.emit(job_id, msg)
            self.progress_updated.emit(job_id, 100, "Failed")
            self.finished.emit(job_id, False, str(e))

    def stop(self):
        self._is_running = False
        self._stopped = True

    def skip(self):
        self._is_running = False
        self._skipped = True
        # Emit skipped status
        self.log_updated.emit(self.job.id, ">>> Skipped by user")
        self.progress_updated.emit(self.job.id, 100, "Skipped")
        self.finished.emit(self.job.id, False, "Skipped by user")

class JobManager(QObject):
    job_added = Signal(JobItem)
    job_removed = Signal(str)
    status_changed = Signal(str, JobStatus)
    progress_changed = Signal(str, int, str) # job_id, progress, status_text
    log_added = Signal(str, str)             # job_id, log_line

    def __init__(self, input_dir, temp_dir, result_dir, config_path):
        super().__init__()
        self.input_dir = input_dir
        self.temp_dir = temp_dir
        self.result_dir = result_dir
        self.config_path = config_path
        self.jobs = {} 
        self.worker = None
        self._batch_running = False

    def get_invalid_jobs(self):
        """非ASCII文字を含むジョブのリストを返す"""
        invalid_jobs = []
        for job in self.jobs.values():
            if job.status == JobStatus.PENDING:
                # ファイル名 (job.name) と パス (job.step_path) 両方をチェック
                try:
                    job.name.encode('ascii')
                    job.step_path.encode('ascii')
                except UnicodeEncodeError:
                    invalid_jobs.append(job)
        return invalid_jobs

    def add_job_from_path(self, step_path):

        path = os.path.abspath(step_path)
        for j in self.jobs.values():
            if os.path.abspath(j.step_path) == path:
                return
                
        name = os.path.splitext(os.path.basename(path))[0]
        job_id = str(uuid.uuid4())[:8]
        job = JobItem(id=job_id, name=name, step_path=path)
        
        # Check if results already exist
        if self._has_existing_results(name):
            job.status = JobStatus.COMPLETED
            job.status_text = "Results Available"
        
        self.jobs[job_id] = job
        self.job_added.emit(job)

    def _has_existing_results(self, job_name):
        """Check if result files exist for this job."""
        graph_path = os.path.join(self.result_dir, f"{job_name}_graph.png")
        return os.path.exists(graph_path)
    
    def cleanup_job_files(self, job_name):
        """Remove temp and result files for a job before re-analysis."""
        import shutil
        
        # Clean temp files: job_name.vtk, job_name.*.vtk, job_name.feb, job_name.log, etc.
        temp_patterns = [
            os.path.join(self.temp_dir, f"{job_name}.vtk"),
            os.path.join(self.temp_dir, f"{job_name}.*.vtk"),
            os.path.join(self.temp_dir, f"{job_name}.feb"),
            os.path.join(self.temp_dir, f"{job_name}.log"),
            os.path.join(self.temp_dir, f"{job_name}_*.vtk"),
            os.path.join(self.temp_dir, f"{job_name}_*.msh"),
        ]
        
        for pattern in temp_patterns:
            for f in glob.glob(pattern):
                try:
                    os.remove(f)
                except Exception:
                    pass
        
        # Clean result files
        result_patterns = [
            os.path.join(self.result_dir, f"{job_name}_*.txt"),
            os.path.join(self.result_dir, f"{job_name}_*.csv"),
            os.path.join(self.result_dir, f"{job_name}_*.png"),
        ]
        
        for pattern in result_patterns:
            for f in glob.glob(pattern):
                try:
                    os.remove(f)
                except Exception:
                    pass


    def remove_job_by_path(self, step_path):
        target_id = None
        path = os.path.abspath(step_path)
        for j_id, j in self.jobs.items():
            if os.path.abspath(j.step_path) == path:
                target_id = j_id
                break
        if target_id:
            del self.jobs[target_id]
            self.job_removed.emit(target_id)

    def start_batch(self):
        # Reset COMPLETED jobs to PENDING and clean up their files
        for job in self.jobs.values():
            if job.status == JobStatus.COMPLETED:
                self.cleanup_job_files(job.name)
                job.status = JobStatus.PENDING
                job.progress = 0
                job.status_text = "Pending"
                self.status_changed.emit(job.id, JobStatus.PENDING)

        self._batch_running = True
        self.start_next_job()

    def start_next_job(self):
        if not self._batch_running:
            return
            
        if self.worker and self.worker.isRunning():
            return
        
        # Natural sort key function (same as GUI list)
        def natural_sort_key(job):
            return [int(text) if text.isdigit() else text.lower()
                    for text in re.split('([0-9]+)', job.name)]
        
        # Sort jobs by name in natural order before finding next PENDING
        sorted_jobs = sorted(self.jobs.values(), key=natural_sort_key)
        
        next_job = None
        for job in sorted_jobs:
            if job.status == JobStatus.PENDING:
                next_job = job
                break
        
        if next_job:
            self.worker = AnalysisWorker(next_job, self.config_path, self.temp_dir, self.result_dir)
            self.worker.progress_updated.connect(self._on_worker_progress)
            self.worker.log_updated.connect(self._on_worker_log)
            self.worker.finished.connect(self._on_worker_finished)
            
            next_job.status = JobStatus.RUNNING
            self.status_changed.emit(next_job.id, JobStatus.RUNNING)
            self.worker.start()
        else:
            self._batch_running = False

    def stop_batch(self):
        self._batch_running = False
        if self.worker:
            self.worker.stop()

    def skip_current_job(self):
        if self.worker and self.worker.isRunning():
            self.worker.skip()

    @Slot(str, int, str)
    def _on_worker_progress(self, job_id, progress, status_text):
        if job_id in self.jobs:
            job = self.jobs[job_id]
            job.progress = progress
            job.status_text = status_text
            self.progress_changed.emit(job_id, progress, status_text)

    @Slot(str, str)
    def _on_worker_log(self, job_id, line):
        if job_id in self.jobs:
            self.jobs[job_id].log_lines.append(line)
            self.log_added.emit(job_id, line)

    @Slot(str, bool, str)
    def _on_worker_finished(self, job_id, success, error_message=""):
        if job_id in self.jobs:
            job = self.jobs[job_id]
            if hasattr(self.worker, '_skipped') and self.worker._skipped:
                job.status = JobStatus.SKIPPED
            elif hasattr(self.worker, '_stopped') and self.worker._stopped:
                job.status = JobStatus.STOPPED
                job.status_text = "Stopped"
                job.error_message = "Force stopped by user"
            elif success:
                job.status = JobStatus.COMPLETED
            else:
                job.status = JobStatus.ERROR
                job.error_message = error_message
            self.status_changed.emit(job_id, job.status)
        
        if self._batch_running:
            self.start_next_job()
