"""
Background Task Manager for Pexels Extension.

Provides a thread-safe task queue system with worker thread pool,
priority levels, cancellation support, and main thread callbacks.

IMPORTANT: This module implements safe callback handling to prevent
StructRNA errors when operator instances are garbage collected.
Callbacks should never capture operator 'self' references.
"""

import threading
import queue
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional, Any, Dict, List


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
        cancellation_token: Event to signal cancellation
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
    cancellation_token: Optional[threading.Event] = field(default=None)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    progress_data: Optional[Dict[str, Any]] = None
    
    def __lt__(self, other: 'Task') -> bool:
        """Compare tasks for priority queue ordering."""
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at
    
    def is_cancellation_requested(self) -> bool:
        """Check if cancellation has been requested."""
        return self.cancellation_token is not None and self.cancellation_token.is_set()


def _is_blender_context_valid() -> bool:
    """
    Check if Blender context is valid for callback execution.
    
    This is crucial for preventing StructRNA errors when callbacks
    are invoked after operator instances have been destroyed.
    
    Returns:
        True if context is valid and safe to use
    """
    try:
        import bpy
        
        # Check if we have a valid context
        if bpy.context is None:
            return False
        
        # Check if scene exists
        if not hasattr(bpy.context, 'scene') or bpy.context.scene is None:
            return False
        
        return True
    except (ReferenceError, AttributeError, RuntimeError, ImportError):
        return False


class TaskManager:
    """
    Thread-safe background task manager with worker thread pool.
    
    Implements singleton pattern to ensure only one task manager exists.
    Provides task submission, cancellation, and status tracking.
    
    IMPORTANT: Callbacks passed to submit_task() should NOT capture
    operator 'self' references. Use CallbackContext from callback_handler.py
    instead to pass data to callbacks safely.
    
    Usage:
        from .callback_handler import (
            SearchCallbackHandler, 
            create_search_context
        )
        
        ctx = create_search_context(query, page, per_page)
        
        task_id = task_manager.submit_task(
            task_func=my_task,
            priority=TaskPriority.NORMAL,
            on_complete=lambda t: SearchCallbackHandler.on_complete(ctx, t),
            on_error=lambda t, e: SearchCallbackHandler.on_error(ctx, t, e),
            on_progress=lambda t: SearchCallbackHandler.on_progress(ctx, t)
        )
    """
    
    _instance: Optional['TaskManager'] = None
    _instance_lock: threading.Lock = threading.Lock()
    
    # Default configuration
    DEFAULT_WORKER_COUNT = 4
    QUEUE_TIMEOUT = 0.1  # Seconds to wait for queue items
    
    def __new__(cls, worker_count: int = DEFAULT_WORKER_COUNT) -> 'TaskManager':
        """Singleton pattern implementation."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance
    
    def __init__(self, worker_count: int = DEFAULT_WORKER_COUNT):
        """
        Initialize the task manager.
        
        Args:
            worker_count: Number of worker threads (default: 4)
        """
        if self._initialized:
            return
        
        self._initialized = True
        self._worker_count = worker_count
        
        # Thread-safe task queue (priority queue)
        self._task_queue: queue.PriorityQueue = queue.PriorityQueue()
        
        # Active tasks dictionary with lock
        self._active_tasks: Dict[str, Task] = {}
        self._tasks_lock = threading.RLock()
        
        # Worker threads
        self._workers: List[threading.Thread] = []
        self._shutdown_event = threading.Event()
        
        # Start worker threads
        self._start_workers()
    
    def _start_workers(self) -> None:
        """Start worker threads."""
        for i in range(self._worker_count):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"PexelsTaskWorker-{i}",
                daemon=True
            )
            worker.start()
            self._workers.append(worker)
    
    def _worker_loop(self) -> None:
        """Main worker thread loop."""
        while not self._shutdown_event.is_set():
            try:
                # Get task from queue with timeout
                task = self._task_queue.get(timeout=self.QUEUE_TIMEOUT)
                
                # Check if task was cancelled before starting
                if task.status == TaskStatus.CANCELLED:
                    self._task_queue.task_done()
                    continue
                
                # Execute the task
                self._execute_task(task)
                self._task_queue.task_done()
                
            except queue.Empty:
                # No tasks available, continue waiting
                continue
            except Exception as e:
                # Log unexpected errors but keep worker running
                print(f"[TaskManager] Worker error: {e}")
    
    def _execute_task(self, task: Task) -> None:
        """
        Execute a single task.
        
        Args:
            task: The task to execute
        """
        # Update task status
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        
        try:
            # Check for cancellation before starting
            if task.is_cancellation_requested():
                task.status = TaskStatus.CANCELLED
                return
            
            # Create progress callback wrapper that stores extra data
            def progress_callback(progress: float, message: str = "", extra_data: Dict = None) -> None:
                self._update_progress(task, progress, message, extra_data)
            
            # Execute the task function
            # Pass cancellation_token and progress_callback as keyword arguments
            task.result = task.func(
                *task.args,
                cancellation_token=task.cancellation_token,
                progress_callback=progress_callback,
                **task.kwargs
            )
            
            # Check for cancellation after completion
            if task.is_cancellation_requested():
                task.status = TaskStatus.CANCELLED
                return
            
            # Mark as completed
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.progress = 1.0
            
            # Schedule completion callback on main thread
            if task.on_complete:
                self._schedule_main_thread_callback(task.on_complete, task)
                
        except InterruptedError:
            # Task was cancelled
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            
        except Exception as e:
            # Task failed
            task.status = TaskStatus.FAILED
            task.error = e
            task.completed_at = time.time()
            
            # Schedule error callback on main thread
            if task.on_error:
                self._schedule_main_thread_callback(task.on_error, task, e)
    
    def _update_progress(
        self, 
        task: Task, 
        progress: float, 
        message: str,
        extra_data: Optional[Dict] = None
    ) -> None:
        """
        Update task progress and notify callbacks.
        
        Args:
            task: The task to update
            progress: Progress value (0.0 to 1.0)
            message: Status message
            extra_data: Additional progress data (e.g., ETA, speed)
        """
        task.progress = max(0.0, min(1.0, progress))
        task.message = message
        task.progress_data = extra_data
        
        # Schedule progress callback on main thread
        if task.on_progress:
            self._schedule_main_thread_callback(task.on_progress, task)
    
    def _schedule_main_thread_callback(self, callback: Callable, *args) -> None:
        """
        Schedule a callback to run on Blender's main thread.
        
        This method implements safe callback execution that:
        1. Validates Blender context before execution
        2. Catches ReferenceError for destroyed RNA structures
        3. Logs errors without crashing
        
        Args:
            callback: The callback function
            *args: Arguments to pass to the callback
        """
        try:
            import bpy
            
            def safe_callback() -> None:
                """
                Wrapper that safely executes the callback.
                
                This prevents StructRNA errors by:
                1. Checking if Blender context is still valid
                2. Catching ReferenceError exceptions
                3. Handling any other exceptions gracefully
                """
                try:
                    # Validate context before executing callback
                    if not _is_blender_context_valid():
                        print("[TaskManager] Callback skipped - Blender context invalid")
                        return None
                    
                    # Execute the callback
                    callback(*args)
                    
                except ReferenceError as e:
                    # This is the StructRNA error we're trying to prevent
                    # It means the operator instance was garbage collected
                    print(f"[TaskManager] Callback skipped - RNA structure removed: {e}")
                    
                except AttributeError as e:
                    # May occur if accessing destroyed objects
                    if "StructRNA" in str(e) or "removed" in str(e).lower():
                        print(f"[TaskManager] Callback skipped - object removed: {e}")
                    else:
                        print(f"[TaskManager] Callback AttributeError: {e}")
                        
                except Exception as e:
                    # Log other errors but don't crash
                    print(f"[TaskManager] Callback error: {e}")
                    
                return None  # Don't repeat the timer
            
            # Register the safe callback with Blender's timer system
            bpy.app.timers.register(safe_callback, first_interval=0.0)
            
        except ImportError:
            # Not running in Blender, execute directly (for testing)
            try:
                callback(*args)
            except Exception as e:
                print(f"[TaskManager] Callback error (non-Blender): {e}")
    
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
        
        The task function should accept these keyword arguments:
        - cancellation_token: threading.Event to check for cancellation
        - progress_callback: Callable[[float, str, dict], None] to report progress
        
        IMPORTANT: Callbacks should NOT capture operator 'self' references.
        Use CallbackContext from callback_handler.py instead.
        
        Example:
            from .callback_handler import (
                SearchCallbackHandler,
                create_search_context
            )
            
            ctx = create_search_context(query, page, per_page)
            
            task_id = task_manager.submit_task(
                task_func=background_search,
                priority=TaskPriority.HIGH,
                on_complete=lambda t: SearchCallbackHandler.on_complete(ctx, t),
                on_error=lambda t, e: SearchCallbackHandler.on_error(ctx, t, e),
                on_progress=lambda t: SearchCallbackHandler.on_progress(ctx, t),
                kwargs={'query': query, 'page': page}
            )
        
        Args:
            task_func: The function to execute
            priority: Task priority (HIGH, NORMAL, LOW)
            on_complete: Callback when task completes successfully
            on_progress: Callback for progress updates
            on_error: Callback when task fails
            args: Positional arguments for task_func
            kwargs: Keyword arguments for task_func
            
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
            on_error=on_error,
            cancellation_token=threading.Event()
        )
        
        # Add to active tasks
        with self._tasks_lock:
            self._active_tasks[task_id] = task
        
        # Add to queue
        self._task_queue.put(task)
        
        return task_id
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Request cancellation of a specific task.
        
        Args:
            task_id: The task ID to cancel
            
        Returns:
            True if task was found and cancellation requested
        """
        with self._tasks_lock:
            if task_id in self._active_tasks:
                task = self._active_tasks[task_id]
                
                # Signal cancellation
                if task.cancellation_token:
                    task.cancellation_token.set()
                
                # Update status if not already running
                if task.status == TaskStatus.PENDING:
                    task.status = TaskStatus.CANCELLED
                
                return True
        return False
    
    def cancel_all(self) -> int:
        """
        Cancel all pending and running tasks.
        
        Returns:
            Number of tasks cancelled
        """
        cancelled_count = 0
        
        with self._tasks_lock:
            for task in self._active_tasks.values():
                if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    if task.cancellation_token:
                        task.cancellation_token.set()
                    if task.status == TaskStatus.PENDING:
                        task.status = TaskStatus.CANCELLED
                    cancelled_count += 1
        
        return cancelled_count
    
    def get_task_status(self, task_id: str) -> Optional[Task]:
        """
        Get the current status of a task.
        
        Args:
            task_id: The task ID to query
            
        Returns:
            Task object or None if not found
        """
        with self._tasks_lock:
            return self._active_tasks.get(task_id)
    
    def get_active_task_count(self) -> int:
        """
        Get the number of active (pending or running) tasks.
        
        Returns:
            Number of active tasks
        """
        with self._tasks_lock:
            return sum(
                1 for task in self._active_tasks.values()
                if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            )
    
    def get_pending_task_count(self) -> int:
        """
        Get the number of pending tasks in the queue.
        
        Returns:
            Number of pending tasks
        """
        return self._task_queue.qsize()
    
    def cleanup_completed_tasks(self, max_age_seconds: float = 300.0) -> int:
        """
        Remove completed/failed/cancelled tasks older than max_age.
        
        Args:
            max_age_seconds: Maximum age in seconds (default: 5 minutes)
            
        Returns:
            Number of tasks removed
        """
        removed_count = 0
        current_time = time.time()
        
        with self._tasks_lock:
            tasks_to_remove = []
            
            for task_id, task in self._active_tasks.items():
                if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    if task.completed_at and (current_time - task.completed_at) > max_age_seconds:
                        tasks_to_remove.append(task_id)
            
            for task_id in tasks_to_remove:
                del self._active_tasks[task_id]
                removed_count += 1
        
        return removed_count
    
    def shutdown(self, wait: bool = True, timeout: float = 2.0) -> None:
        """
        Shutdown the task manager and stop all workers.
        
        Args:
            wait: Whether to wait for workers to finish
            timeout: Maximum time to wait for each worker
        """
        # Signal shutdown
        self._shutdown_event.set()
        
        # Cancel all pending tasks
        self.cancel_all()
        
        if wait:
            # Wait for workers to finish
            for worker in self._workers:
                worker.join(timeout=timeout)
        
        # Clear workers list
        self._workers.clear()
        
        # Reset initialization flag for potential restart
        self._initialized = False
        TaskManager._instance = None
    
    def is_running(self) -> bool:
        """
        Check if the task manager is running.
        
        Returns:
            True if task manager is active
        """
        return self._initialized and not self._shutdown_event.is_set()


# Global instance
task_manager = TaskManager()


def get_task_manager() -> TaskManager:
    """
    Get the global task manager instance.
    
    Returns:
        TaskManager instance
    """
    return task_manager