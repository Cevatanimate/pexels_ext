"""
Background Task Manager for Pexels Extension.

Provides a multiprocessing task queue system with worker pool,
priority levels, cancellation support, and main thread callbacks.

IMPORTANT: This module implements safe callback handling to prevent
StructRNA errors when operator instances are garbage collected.
Callbacks should never capture operator 'self' references.
"""

import multiprocessing
import threading
import queue
import time
import uuid
import traceback
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional, Any, Dict, List, Tuple

# Try to import bpy, but handle failure for worker processes
try:
    import bpy
except ImportError:
    bpy = None


class TaskPriority(IntEnum):
    """Task priority levels. Lower values = higher priority."""
    HIGH = 0
    NORMAL = 1
    LOW = 2


class TaskStatus(IntEnum):
    """Task execution status."""
    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3
    CANCELLED = 4
    PROGRESS = 5


@dataclass
class Task:
    """
    Represents a background task with all its metadata and callbacks.
    
    Attributes:
        id: Unique task identifier
        func: The callable to execute
        args: Positional arguments for the function
        kwargs: Keyword arguments for the function
        priority: Task priority level
        status: Current task status
        progress: Progress percentage (0.0 to 1.0)
        message: Current status message
        result: Task result after completion
        error: Exception if task failed
        on_progress: Callback for progress updates (called on main thread)
        on_complete: Callback when task completes (called on main thread)
        on_error: Callback when task fails (called on main thread)
        created_at: Timestamp when task was created
        started_at: Timestamp when task started executing
        completed_at: Timestamp when task finished
        progress_data: Additional progress data (dict)
    """
    id: str
    func: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    message: str = ""
    result: Any = None
    error: Optional[Exception] = None
    on_progress: Optional[Callable[['Task'], None]] = None
    on_complete: Optional[Callable[['Task'], None]] = None
    on_error: Optional[Callable[['Task', Exception], None]] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress_data: Optional[Dict[str, Any]] = None
    
    def __lt__(self, other: 'Task') -> bool:
        """Compare tasks for priority queue ordering."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at


def _worker_process(
    input_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    shutdown_event: multiprocessing.Event
) -> None:
    """
    Worker process function.
    
    Args:
        input_queue: Queue to receive tasks
        result_queue: Queue to send results
        shutdown_event: Event to signal shutdown
    """
    while not shutdown_event.is_set():
        try:
            # Get task from queue with timeout
            try:
                task_data = input_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            
            task_id, func, args, kwargs = task_data
            
            # Report running
            result_queue.put((task_id, TaskStatus.RUNNING, None, None))
            
            try:
                # Create progress callback
                def progress_callback(progress: float, message: str = "", extra_data: Dict = None) -> None:
                    result_queue.put((
                        task_id, 
                        TaskStatus.PROGRESS, 
                        None, 
                        {'progress': progress, 'message': message, 'extra_data': extra_data}
                    ))
                
                # Execute task
                # Note: We don't pass cancellation_token anymore as it's hard to share across processes
                # reliably without a manager. Tasks should be short or check their own logic.
                # We pass progress_callback if the function accepts it.
                
                # Simple inspection to see if we should pass progress_callback
                # This is a bit hacky but works for our known tasks
                import inspect
                try:
                    sig = inspect.signature(func)
                    if 'progress_callback' in sig.parameters:
                        kwargs['progress_callback'] = progress_callback
                except Exception:
                    pass
                
                result = func(*args, **kwargs)
                
                # Report success
                result_queue.put((task_id, TaskStatus.COMPLETED, result, None))
                
            except Exception as e:
                # Report failure
                # We send the exception string to avoid pickling issues with complex exceptions
                result_queue.put((task_id, TaskStatus.FAILED, str(e), None))
                
        except Exception as e:
            # Fatal worker error
            print(f"[TaskManager] Worker process error: {e}")
            time.sleep(1.0)


def _is_blender_context_valid() -> bool:
    """Check if Blender context is valid."""
    try:
        if bpy is None or bpy.context is None:
            return False
        if not hasattr(bpy.context, 'scene') or bpy.context.scene is None:
            return False
        return True
    except (ReferenceError, AttributeError, RuntimeError, ImportError):
        return False


class TaskManager:
    """
    Multiprocessing background task manager.
    
    Implements singleton pattern (lazy loaded).
    """
    
    _instance: Optional['TaskManager'] = None
    
    # Default configuration
    DEFAULT_WORKER_COUNT = 4
    
    def __init__(self, worker_count: int = DEFAULT_WORKER_COUNT):
        """Initialize the task manager."""
        self._worker_count = worker_count
        
        # Multiprocessing queues
        self._input_queue = multiprocessing.Queue()
        self._result_queue = multiprocessing.Queue()
        self._shutdown_event = multiprocessing.Event()
        
        # Active tasks dictionary (in main process)
        self._active_tasks: Dict[str, Task] = {}
        self._tasks_lock = threading.RLock()
        
        # Worker processes
        self._workers: List[multiprocessing.Process] = []
        
        # Start workers
        self._start_workers()
        
        # Start result poller
        self._start_result_poller()
    
    def _start_workers(self) -> None:
        """Start worker processes."""
        for i in range(self._worker_count):
            worker = multiprocessing.Process(
                target=_worker_process,
                args=(self._input_queue, self._result_queue, self._shutdown_event),
                name=f"PexelsWorker-{i}",
                daemon=True
            )
            worker.start()
            self._workers.append(worker)
    
    def _start_result_poller(self) -> None:
        """Start the result polling timer in Blender."""
        if bpy:
            bpy.app.timers.register(self._poll_results, first_interval=0.1)
    
    def _poll_results(self) -> float:
        """
        Poll for results from worker processes.
        Returns delay for next poll.
        """
        if self._shutdown_event.is_set():
            return None  # Stop timer
        
        try:
            # Process up to 10 results per tick to avoid freezing UI
            for _ in range(10):
                try:
                    result_data = self._result_queue.get_nowait()
                except queue.Empty:
                    break
                
                task_id, status, result_or_error, progress_info = result_data
                self._handle_task_update(task_id, status, result_or_error, progress_info)
                
        except Exception as e:
            print(f"[TaskManager] Polling error: {e}")
        
        return 0.1  # Poll every 100ms
    
    def _handle_task_update(
        self, 
        task_id: str, 
        status: TaskStatus, 
        result_or_error: Any, 
        progress_info: Optional[Dict]
    ) -> None:
        """Handle task update on main thread."""
        with self._tasks_lock:
            task = self._active_tasks.get(task_id)
            if not task:
                return
            
            if status == TaskStatus.RUNNING:
                task.status = TaskStatus.RUNNING
                task.started_at = time.time()
                
            elif status == TaskStatus.PROGRESS:
                if progress_info:
                    task.progress = progress_info.get('progress', 0.0)
                    task.message = progress_info.get('message', "")
                    task.progress_data = progress_info.get('extra_data')
                    if task.on_progress:
                        self._safe_callback(task.on_progress, task)
                        
            elif status == TaskStatus.COMPLETED:
                task.status = TaskStatus.COMPLETED
                task.result = result_or_error
                task.completed_at = time.time()
                task.progress = 1.0
                if task.on_complete:
                    self._safe_callback(task.on_complete, task)
                # We keep the task in _active_tasks for a while or until cleanup
                
            elif status == TaskStatus.FAILED:
                task.status = TaskStatus.FAILED
                # Reconstruct exception from string if needed, or just store string
                task.error = Exception(result_or_error) if isinstance(result_or_error, str) else result_or_error
                task.completed_at = time.time()
                if task.on_error:
                    self._safe_callback(task.on_error, task, task.error)
    
    def _safe_callback(self, callback: Callable, *args) -> None:
        """Execute callback safely."""
        try:
            if not _is_blender_context_valid():
                return
            callback(*args)
        except Exception as e:
            print(f"[TaskManager] Callback error: {e}")
    
    def submit_task(
        self,
        task_func: Callable,
        priority: TaskPriority = TaskPriority.NORMAL,
        on_complete: Optional[Callable[['Task'], None]] = None,
        on_progress: Optional[Callable[['Task'], None]] = None,
        on_error: Optional[Callable[['Task', Exception], None]] = None,
        args: tuple = (),
        kwargs: Optional[dict] = None
    ) -> str:
        """
        Submit a task for background execution.
        
        Args:
            task_func: The function to execute (must be picklable)
            priority: Task priority (currently ignored by multiprocessing queue)
            on_complete: Callback when task completes
            on_progress: Callback for progress updates
            on_error: Callback when task fails
            args: Positional arguments
            kwargs: Keyword arguments
            
        Returns:
            Task ID string
        """
        task_id = str(uuid.uuid4())
        
        task = Task(
            id=task_id,
            func=task_func,
            args=args,
            kwargs=kwargs or {},
            priority=priority,
            on_complete=on_complete,
            on_progress=on_progress,
            on_error=on_error
        )
        
        with self._tasks_lock:
            self._active_tasks[task_id] = task
        
        # Put simplified payload into queue
        # Note: func, args, kwargs must be picklable
        self._input_queue.put((task_id, task_func, args, kwargs or {}))
        
        return task_id
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Request cancellation of a task.
        Note: With multiprocessing, we can't easily interrupt a running process
        without terminating it. This implementation only cancels pending tasks.
        """
        with self._tasks_lock:
            if task_id in self._active_tasks:
                task = self._active_tasks[task_id]
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED
                    return True
        return False
    
    def cancel_all(self) -> int:
        """Cancel all pending tasks."""
        count = 0
        with self._tasks_lock:
            for task in self._active_tasks.values():
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED
                    count += 1
        return count
    
    def get_task_status(self, task_id: str) -> Optional[Task]:
        """Get task status."""
        with self._tasks_lock:
            return self._active_tasks.get(task_id)
    
    def shutdown(self) -> None:
        """Shutdown the task manager."""
        self._shutdown_event.set()
        
        # Terminate workers
        for worker in self._workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=0.1)
        
        self._workers.clear()
        
        # Clear queues
        while not self._input_queue.empty():
            try:
                self._input_queue.get_nowait()
            except queue.Empty:
                break
                
        global task_manager
        task_manager = None


# Global instance (lazy loaded)
task_manager = None

def get_task_manager() -> TaskManager:
    """Get the global task manager instance."""
    global task_manager
    if task_manager is None:
        task_manager = TaskManager()
    return task_manager