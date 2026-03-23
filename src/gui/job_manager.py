import glob
import os
import re
import uuid

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

import analysis_helpers as helpers
from src.config_loader import AnalysisConfig
from src.gui.models.job_item import JobItem, JobStatus


class AnalysisWorker(QThread):
    progress_updated = Signal(str, int, str)
    log_updated = Signal(str, str)
    finished = Signal(str, bool, str)

    def __init__(
        self,
        job: JobItem,
        config_path: str,
        temp_dir: str,
        result_dir: str,
        mesh_only: bool = False,
    ):
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
            value = 20 + int(percent * 0.79)
            self.progress_updated.emit(job_id, value, f"Solving ({percent}%)")

        def check_stop():
            return not self._is_running

        def finish_if_stopped():
            if self._is_running:
                return False
            if self._skipped:
                self.finished.emit(job_id, False, "Skipped by user")
            else:
                self.finished.emit(job_id, False, "Stopped by user")
            return True

        try:
            analysis_config = AnalysisConfig.from_yaml(self.config_path)
            push_dist = -1.0 * abs(analysis_config.total_stroke)
            sim_steps = analysis_config.time_steps
            febio_path = analysis_config.febio_path or None
            template_path = analysis_config.template_feb
            material_name = analysis_config.material_name
            num_threads = analysis_config.num_threads
            contact_penalty = analysis_config.contact_penalty
            material_config_path = os.path.join(
                os.path.dirname(self.config_path), "material.yaml"
            )

            log_path = os.path.join(self.temp_dir, f"{base_name}.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"=== Analysis Log for {base_name} ===\n")

            self.progress_updated.emit(job_id, 1, "Meshing...")
            try:
                vtk_path = helpers.run_meshing(
                    self.job.step_path,
                    self.config_path,
                    self.temp_dir,
                    log_path=log_path,
                    log_callback=log_cb,
                    check_stop_callback=check_stop,
                )
            except KeyboardInterrupt:
                if finish_if_stopped():
                    return
                raise

            self.job.vtk_path = vtk_path
            self.progress_updated.emit(job_id, 5, "Mesh Complete")

            if finish_if_stopped():
                return

            if self.mesh_only:
                self.progress_updated.emit(job_id, 100, "Mesh Generated")
                self.finished.emit(job_id, True, "Mesh Generation Complete")
                return

            self.progress_updated.emit(job_id, 10, "Preparing FEBio model...")
            out_feb = os.path.join(self.temp_dir, f"{base_name}.feb")
            helpers.run_integration(
                vtk_path,
                template_path,
                out_feb,
                push_dist,
                sim_steps,
                material_name,
                material_config_path,
                contact_penalty=contact_penalty,
                log_path=log_path,
            )
            self.job.feb_path = out_feb
            self.progress_updated.emit(job_id, 15, "Prep Complete")

            if finish_if_stopped():
                return

            self.progress_updated.emit(job_id, 20, "Solving (0%)")
            success = helpers.run_solver_and_extract(
                out_feb,
                self.result_dir,
                log_path=log_path,
                num_threads=num_threads,
                febio_exe=febio_path,
                log_callback=log_cb,
                progress_callback=prog_cb,
                check_stop_callback=check_stop,
            )

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

        except Exception as error:
            self.log_updated.emit(job_id, f"Worker Error: {error}")
            self.progress_updated.emit(job_id, 100, "Failed")
            self.finished.emit(job_id, False, str(error))

    def stop(self):
        self._is_running = False
        self._stopped = True

    def skip(self):
        self._is_running = False
        self._skipped = True
        self.log_updated.emit(self.job.id, ">>> Skipped by user")
        self.progress_updated.emit(self.job.id, 100, "Skipping...")


class JobManager(QObject):
    job_added = Signal(JobItem)
    job_removed = Signal(str)
    status_changed = Signal(str, JobStatus)
    progress_changed = Signal(str, int, str)
    log_added = Signal(str, str)
    batch_finished = Signal()

    def __init__(self, input_dir, temp_dir, result_dir, config_path):
        super().__init__()
        self.input_dir = input_dir
        self.temp_dir = temp_dir
        self.result_dir = result_dir
        self.config_path = config_path
        self.jobs = {}
        self._job_ids_by_path = {}
        self.worker = None
        self._batch_running = False
        self._batch_mesh_only = False

    @staticmethod
    def _normalize_path(step_path):
        return os.path.normcase(os.path.abspath(step_path))

    def get_invalid_jobs(self):
        invalid_jobs = []
        for job in self.jobs.values():
            if job.status == JobStatus.PENDING:
                try:
                    job.name.encode("ascii")
                    job.step_path.encode("ascii")
                except UnicodeEncodeError:
                    invalid_jobs.append(job)
        return invalid_jobs

    def add_job_from_path(self, step_path):
        path = os.path.abspath(step_path)
        normalized_path = self._normalize_path(path)
        if normalized_path in self._job_ids_by_path:
            return
        if not os.path.exists(path):
            return

        name = os.path.splitext(os.path.basename(path))[0]
        job_id = str(uuid.uuid4())[:8]
        job = JobItem(id=job_id, name=name, step_path=path)

        if self._has_existing_results(name):
            job.status = JobStatus.COMPLETED
            job.status_text = "Results Available"

        self.jobs[job_id] = job
        self._job_ids_by_path[normalized_path] = job_id
        self.job_added.emit(job)

    @Slot(list)
    def sync_input_files(self, step_paths):
        current_paths = set(self._job_ids_by_path)
        desired_paths = {
            self._normalize_path(path): os.path.abspath(path) for path in step_paths
        }

        removed_paths = current_paths - set(desired_paths)
        added_paths = sorted(set(desired_paths) - current_paths, key=str.lower)

        for normalized_path in removed_paths:
            job_id = self._job_ids_by_path.get(normalized_path)
            if job_id is None:
                continue
            job = self.jobs.pop(job_id, None)
            self._job_ids_by_path.pop(normalized_path, None)
            if job is not None:
                self.job_removed.emit(job_id)

        for normalized_path in added_paths:
            self.add_job_from_path(desired_paths[normalized_path])

    def _has_existing_results(self, job_name):
        graph_path = os.path.join(self.result_dir, f"{job_name}_graph.png")
        return os.path.exists(graph_path)

    def cleanup_job_files(self, job_name):
        temp_patterns = [
            os.path.join(self.temp_dir, f"{job_name}.vtk"),
            os.path.join(self.temp_dir, f"{job_name}.*.vtk"),
            os.path.join(self.temp_dir, f"{job_name}.feb"),
            os.path.join(self.temp_dir, f"{job_name}.log"),
            os.path.join(self.temp_dir, f"{job_name}_*.vtk"),
            os.path.join(self.temp_dir, f"{job_name}_*.msh"),
        ]

        for pattern in temp_patterns:
            for path in glob.glob(pattern):
                try:
                    os.remove(path)
                except Exception:
                    pass

        result_patterns = [
            os.path.join(self.result_dir, f"{job_name}_*.txt"),
            os.path.join(self.result_dir, f"{job_name}_*.csv"),
            os.path.join(self.result_dir, f"{job_name}_*.png"),
        ]

        for pattern in result_patterns:
            for path in glob.glob(pattern):
                try:
                    os.remove(path)
                except Exception:
                    pass

    def remove_job_by_path(self, step_path):
        normalized_path = self._normalize_path(step_path)
        target_id = self._job_ids_by_path.pop(normalized_path, None)
        if target_id:
            self.jobs.pop(target_id, None)
            self.job_removed.emit(target_id)

    def start_batch(self, mesh_only=False):
        reset_statuses = [
            JobStatus.COMPLETED,
            JobStatus.MESH_GENERATED,
            JobStatus.STOPPED,
            JobStatus.SKIPPED,
            JobStatus.ERROR,
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

        def natural_sort_key(job):
            return [
                int(text) if text.isdigit() else text.lower()
                for text in re.split(r"([0-9]+)", job.name)
            ]

        sorted_jobs = sorted(self.jobs.values(), key=natural_sort_key)

        next_job = None
        for job in sorted_jobs:
            if job.status == JobStatus.PENDING:
                next_job = job
                break

        if next_job:
            self.worker = AnalysisWorker(
                next_job,
                self.config_path,
                self.temp_dir,
                self.result_dir,
                mesh_only=self._batch_mesh_only,
            )
            self.worker.progress_updated.connect(self._on_worker_progress)
            self.worker.log_updated.connect(self._on_worker_log)
            self.worker.finished.connect(self._on_worker_finished)

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
            if hasattr(self.worker, "_skipped") and self.worker._skipped:
                job.status = JobStatus.SKIPPED
            elif hasattr(self.worker, "_stopped") and self.worker._stopped:
                job.status = JobStatus.STOPPED
                job.status_text = "Stopped"
                job.error_message = "Force stopped by user"
            elif success:
                if hasattr(self.worker, "mesh_only") and self.worker.mesh_only:
                    job.status = JobStatus.MESH_GENERATED
                else:
                    job.status = JobStatus.COMPLETED
            else:
                job.status = JobStatus.ERROR
                job.error_message = error_message
            self.status_changed.emit(job_id, job.status)

        if self._batch_running:
            QTimer.singleShot(100, self.start_next_job)
