import os
import logging
import uuid
from typing import Callable, Any, Optional, Dict
from concurrent.futures import ThreadPoolExecutor, Future
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore

logger = logging.getLogger(__name__)


class TaskRunner:
    """
    Background task runner with ThreadPoolExecutor for async tasks.
    Supports progress tracking via in-memory store (use Redis in production).
    """

    def __init__(self):
        self.thread_pool = ThreadPoolExecutor(max_workers=4)
        self.scheduler = BackgroundScheduler(jobstores={'default': MemoryJobStore()})
        self.scheduler.start()
        self._progress_store: Dict[str, Dict] = {}
        logger.info("TaskRunner initialized with ThreadPoolExecutor and APScheduler")

    def submit_task(self, func: Callable, *args, **kwargs) -> str:
        """
        Submit a task for background execution.
        Returns task ID for progress tracking.
        """
        task_id = str(uuid.uuid4())

        # Initialize progress tracking
        self._progress_store[task_id] = {
            'progress': 0.0,
            'message': 'Queued',
            'status': 'pending',
            'result': None,
            'error': None
        }

        # If function accepts progress_callback, inject it
        import inspect
        sig = inspect.signature(func)
        if 'progress_callback' in sig.parameters:
            kwargs['progress_callback'] = lambda p, m: self._update_progress(task_id, p, m)

        # Submit to thread pool
        future: Future = self.thread_pool.submit(self._run_with_progress, func, task_id, *args, **kwargs)
        # Store future reference to prevent garbage collection
        self._progress_store[task_id]['_future'] = future

        return task_id

    def _run_with_progress(self, func: Callable, task_id: str, *args, **kwargs):
        """Run function with progress updates via callback."""
        try:
            self._update_progress(task_id, 0.1, "Starting...")
            result = func(*args, **kwargs)
            self._update_progress(task_id, 1.0, "Completed", status='completed', result=result)
            return result
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            self._update_progress(task_id, -1.0, f"Error: {str(e)}", status='failed', error=str(e))
            raise

    def _update_progress(self, task_id: str, progress: float, message: str,
                         status: Optional[str] = None, result: Any = None, error: Optional[str] = None):
        """Update task progress in memory store."""
        if task_id in self._progress_store:
            entry = self._progress_store[task_id]
            entry['progress'] = max(0.0, min(1.0, progress)) if progress >= 0 else -1.0
            entry['message'] = message
            if status:
                entry['status'] = status
            if result is not None:
                entry['result'] = result
            if error is not None:
                entry['error'] = error
            logger.info(f"Task {task_id}: {progress*100:.0f}% - {message}")

    def get_progress(self, task_id: str) -> Optional[Dict]:
        """Get current progress for a task."""
        entry = self._progress_store.get(task_id)
        if not entry:
            return None
        # Return copy without internal fields
        return {
            'task_id': task_id,
            'progress': entry['progress'],
            'message': entry['message'],
            'status': entry['status'],
            'result': entry['result'],
            'error': entry['error']
        }

    def cancel_task(self, task_id: str) -> bool:
        """Attempt to cancel a running task."""
        entry = self._progress_store.get(task_id)
        if entry and '_future' in entry:
            future = entry['_future']
            if future.cancel():
                self._update_progress(task_id, -1.0, "Cancelled", status='cancelled')
                return True
        return False

    def schedule_recurring(self, func: Callable, interval_seconds: int, *args, **kwargs) -> str:
        """Schedule a recurring task."""
        job = self.scheduler.add_job(func, 'interval', seconds=interval_seconds, args=args, kwargs=kwargs)
        return job.id

    def shutdown(self):
        """Clean shutdown."""
        self.scheduler.shutdown()
        self.thread_pool.shutdown(wait=True)
        logger.info("TaskRunner shutdown complete")


# Lazy-initialized global instance (only created when accessed)
_task_runner_instance: Optional[TaskRunner] = None


def get_task_runner() -> TaskRunner:
    """Get or create the global TaskRunner instance."""
    global _task_runner_instance
    if _task_runner_instance is None:
        _task_runner_instance = TaskRunner()
    return _task_runner_instance