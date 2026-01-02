import os
import uuid
import time
import yaml
from PySide6.QtCore import QObject, QThread, Signal, Slot
from src.gui.models.job_item import JobItem, JobStatus
import analysis_helpers as helpers

class AnalysisWorker(QThread):
    progress_updated = Signal(str, int, str) # job_id, progress, status_text
    log_updated = Signal(str, str)           # job_id, log_line
    finished = Signal(str, bool)             # job_id, success

    def __init__(self, job: JobItem, config_path: str, temp_dir: str, result_dir: str):
        super().__init__()
        self.job = job
        self.config_path = config_path
        self.temp_dir = temp_dir
        self.result_dir = result_dir
        self._is_running = True

    def run(self):
        job_id = self.job.id
        base_name = self.job.name
        
        def log_cb(line):
            self.log_updated.emit(job_id, line)
            
        def prog_cb(percent):
            # Scale solver percentage (60-99%)
            val = 60 + int(percent * 0.39)
            self.progress_updated.emit(job_id, val, f"Solving ({percent}%)")

        try:
            # --- Load Config ---
            push_dist, sim_steps = -1.0, 20
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    conf = yaml.safe_load(f).get("analysis", {})
                    push_dist = conf.get("push_dist", push_dist)
                    sim_steps = conf.get("time_steps", sim_steps)

            # --- 1. Meshing ---
            self.progress_updated.emit(job_id, 5, "Meshing...")
            vtk_path = helpers.run_meshing(self.job.step_path, self.config_path, self.temp_dir, log_callback=log_cb)
            self.job.vtk_path = vtk_path
            self.progress_updated.emit(job_id, 30, "Mesh Complete")
            
            if not self._is_running: return

            # --- 2. Integration ---
            self.progress_updated.emit(job_id, 40, "Preparing FEBio model...")
            out_feb = os.path.join(self.temp_dir, f"{base_name}.feb")
            helpers.run_integration(vtk_path, helpers.DEFAULT_TEMPLATE, out_feb, push_dist, sim_steps)
            self.job.feb_path = out_feb
            self.progress_updated.emit(job_id, 55, "Prep Complete")
            
            if not self._is_running: return

            # --- 3. Solver ---
            self.progress_updated.emit(job_id, 60, "Solving (0%)")
            success = helpers.run_solver_and_extract(
                out_feb, self.result_dir, 
                log_callback=log_cb, 
                progress_callback=prog_cb
            )
            
            if success:
                self.progress_updated.emit(job_id, 100, "Completed")
                self.finished.emit(job_id, True)
            else:
                self.progress_updated.emit(job_id, 100, "Error")
                self.finished.emit(job_id, False)

        except Exception as e:
            msg = f"Worker Error: {str(e)}"
            self.log_updated.emit(job_id, msg)
            self.progress_updated.emit(job_id, 100, "Failed")
            self.finished.emit(job_id, False)

    def stop(self):
        self._is_running = False

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

    def add_job_from_path(self, step_path):
        path = os.path.abspath(step_path)
        for j in self.jobs.values():
            if os.path.abspath(j.step_path) == path:
                return
                
        name = os.path.splitext(os.path.basename(path))[0]
        job_id = str(uuid.uuid4())[:8]
        job = JobItem(id=job_id, name=name, step_path=path)
        self.jobs[job_id] = job
        self.job_added.emit(job)

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
        self._batch_running = True
        self.start_next_job()

    def start_next_job(self):
        if not self._batch_running:
            return
            
        if self.worker and self.worker.isRunning():
            return
            
        next_job = None
        for job in self.jobs.values():
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

    @Slot(str, bool)
    def _on_worker_finished(self, job_id, success):
        if job_id in self.jobs:
            job = self.jobs[job_id]
            job.status = JobStatus.COMPLETED if success else JobStatus.ERROR
            self.status_changed.emit(job_id, job.status)
        
        if self._batch_running:
            self.start_next_job()
