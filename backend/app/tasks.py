from celery import Celery
import importlib
import logging
from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery('khmerdub', broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

@celery_app.task(bind=True, name='app.tasks.execute_job')
def execute_job(self, func_name: str, args: list, kwargs: dict, task_id: str):
    """Execute a background job by importing and calling the function."""
    try:
        # Import the service module dynamically
        # Functions are expected to be in app.services.<module>
        module_name = kwargs.pop('_module', 'app.services.dubbing_pipeline')
        module = importlib.import_module(module_name)
        func = getattr(module, func_name)

        # Update progress
        self.update_state(state='PROGRESS', meta={'progress': 0.1, 'message': f'Starting {func_name}...'})

        result = func(*args, **kwargs)

        self.update_state(state='SUCCESS', meta={'progress': 1.0, 'message': 'Completed', 'result': result})
        return result
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        self.update_state(state='FAILURE', meta={'progress': -1.0, 'message': str(e)})
        raise