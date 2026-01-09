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

    def __init__(self, job: JobItem, config_path: str, temp_dir: str, result_dir: str, mesh_only: bool = False):
        super().__init__()
        self.job = job
        self.config_path = config_path
        self.temp_dir = temp_dir
        self.result_dir = result_dir
        self.mesh_only = mesh_only
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
            push_dist, sim_steps = None, None  # Noneで「上書きしない」を表現
            febio_path = None
            template_name = "template2.feb"
            material_name = None
            num_threads = None
            
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    conf = yaml.safe_load(f).get("analysis", {})
                    # total_stroke優先、push_dist互換 (main.pyと同様)
                    if "total_stroke" in conf:
                        push_dist = -1.0 * abs(float(conf["total_stroke"]))
                    elif "push_dist" in conf:
                        push_dist = float(conf["push_dist"])
                    sim_steps = conf.get("time_steps")
                    febio_path = conf.get("febio_path")
                    template_name = conf.get("template_feb", template_name)
                    material_name = conf.get("material_name")
                    num_threads = conf.get("num_threads")

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

            # Callback to check if stopped/skipped from GUI thread
            def check_stop():
                return not self._is_running

            # --- 1. Meshing ---
            self.progress_updated.emit(job_id, 1, "Meshing...")
            try:
                vtk_path = helpers.run_meshing(self.job.step_path, self.config_path, self.temp_dir, 
                                             log_path=log_path, log_callback=log_cb, 
                                             check_stop_callback=check_stop)
            except KeyboardInterrupt:
                if self._skipped:
                    self.finished.emit(job_id, False, "Skipped by user")
                    return
                if self._stopped:
                    self.finished.emit(job_id, False, "Stopped by user")
                    return
                # If unknown interrupt, re-raise
                raise
            
            self.job.vtk_path = vtk_path
            self.progress_updated.emit(job_id, 5, "Mesh Complete")
            
            if not self._is_running: 
                if self._skipped: self.finished.emit(job_id, False, "Skipped by user")
                else: self.finished.emit(job_id, False, "Stopped by user")
                return

            if self.mesh_only:
                self.progress_updated.emit(job_id, 100, "Mesh Generated")
                self.finished.emit(job_id, True, "Mesh Generation Complete")
                return

            # --- 2. Integration ---
            self.progress_updated.emit(job_id, 10, "Preparing FEBio model...")
            out_feb = os.path.join(self.temp_dir, f"{base_name}.feb")
            # material.yamlのパスを解決
            material_config_path = os.path.join(os.path.dirname(self.config_path), "material.yaml")
            helpers.run_integration(
                vtk_path, template_path, out_feb,
                push_dist, sim_steps,
                material_name, material_config_path,
                log_path=log_path
            )
            self.job.feb_path = out_feb
            self.progress_updated.emit(job_id, 15, "Prep Complete")
            
            if not self._is_running: 
                if self._skipped: self.finished.emit(job_id, False, "Skipped by user")
                else: self.finished.emit(job_id, False, "Stopped by user")
                return

            # --- 3. Solver ---
            self.progress_updated.emit(job_id, 20, "Solving (0%)")
            
            success = helpers.run_solver_and_extract(
                out_feb, self.result_dir, 
                log_path=log_path,
                num_threads=num_threads,
                febio_exe=febio_path,
                log_callback=log_cb, 
                progress_callback=prog_cb,
                check_stop_callback=check_stop
            )
            
            # If manually stopped or skipped (via check_stop_callback in solver loop)
            if self._stopped:
                self.progress_updated.emit(job_id, 100, "Stopped")
                self.finished.emit(job_id, False, "Stopped by user")
                return
            if self._skipped:
                self.progress_updated.emit(job_id, 100, "Skipped")
                self.finished.emit(job_id, False, "Skipped by user")
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
        # finished signal will be emitted in run()

    def skip(self):
        self._is_running = False
        self._skipped = True
        # Emit skipped status update immediately for UI feedback, but do NOT emit finished yet
        self.log_updated.emit(self.job.id, ">>> Skipped by user")
        self.progress_updated.emit(self.job.id, 100, "Skipping...")

class JobManager(QObject):
    job_added = Signal(JobItem)
    job_removed = Signal(str)
    status_changed = Signal(str, JobStatus)
    progress_changed = Signal(str, int, str) # job_id, progress, status_text
    log_added = Signal(str, str)             # job_id, log_line
    batch_finished = Signal()                # Emitted when all jobs in batch are done

    def __init__(self, input_dir, temp_dir, result_dir, config_path):
        super().__init__()
        self.input_dir = input_dir
        self.temp_dir = temp_dir
        self.result_dir = result_dir
        self.config_path = config_path
        self.jobs = {} 
        self.worker = None
        self._batch_running = False
        self._batch_mesh_only = False

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

    def start_batch(self, mesh_only=False):
        # Reset ALL non-pending jobs to PENDING and clean up their files
        # This ensures that after Stop, pressing Start will run from the beginning
        reset_statuses = [
            JobStatus.COMPLETED, 
            JobStatus.MESH_GENERATED, 
            JobStatus.STOPPED, 
            JobStatus.SKIPPED,
            JobStatus.ERROR
        ]
        for job in self.jobs.values():
            if job.status in reset_statuses:
                self.cleanup_job_files(job.name)
                job.status = JobStatus.PENDING
                job.progress = 0
                job.status_text = "Pending"
                self.status_changed.emit(job.id, JobStatus.PENDING)

        self._batch_running = True
        self._batch_mesh_only = mesh_only
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
            self.worker = AnalysisWorker(next_job, self.config_path, self.temp_dir, self.result_dir, mesh_only=self._batch_mesh_only)
            self.worker.progress_updated.connect(self._on_worker_progress)
            self.worker.log_updated.connect(self._on_worker_log)
            # Custom signal for status updates
            self.worker.finished.connect(self._on_worker_finished) 
            # Standard QThread signal for safe sequencing (wait for thread to actually die)
            # Note: AnalysisWorker defines 'finished', so accessing QThread.finished requires casting or careful binding?
            # Actually, AnalysisWorker.finished shadows QThread.finished.
            # We must rename the custom signal in AnalysisWorker or use a different connection.
            # But changing AnalysisWorker signature is invasive.
            # Let's use the 'finished()' from QThread by connecting to the worker itself as a QThread object?
            # Or simplified: AnalysisWorker emits its custom finished signal at the VERY END of run().
            # So if we trust run() to return immediately after emitting, the race is small.
            # However, the previous code had 'return' immediately after emit inside run(), so it should be fine IF we removed the early emit in skip().
            # Since we did remove the early emit in skip(), the custom signal is now ONLY emitted when run() is returning.
            # So we can keep using custom signal for sequencing, as isRunning() will flip shortly.
            # BUT to be 100% safe, let's verify if we need to wait.
            
            # Since we fixed skip() to NOT emit finished, the race is resolved.
            # The finished signal now effectively means "Thread is done".
            # So start_next_job called from on_worker_finished might still see isRunning=True for a microsecond.
            # So let's wrap start_next_job call in a small delay or use QTimer.singleShot(0, ...)
            
            next_job.status = JobStatus.RUNNING
            self.status_changed.emit(next_job.id, JobStatus.RUNNING)
            self.worker.start()
        else:
            self._batch_running = False
            self.batch_finished.emit()

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
                if hasattr(self.worker, 'mesh_only') and self.worker.mesh_only:
                    job.status = JobStatus.MESH_GENERATED
                else:
                    job.status = JobStatus.COMPLETED
            else:
                job.status = JobStatus.ERROR
                job.error_message = error_message
            self.status_changed.emit(job_id, job.status)
        
        if self._batch_running:
            # Delay slightly to allow the thread to fully exit and isRunning() to become False
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self.start_next_job)
