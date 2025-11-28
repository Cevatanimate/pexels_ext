"""
Progress Tracker for Pexels Extension.

Provides real-time progress tracking with ETA estimation using moving average.
Thread-safe implementation with callback support for UI updates.
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Callable, Dict, Any
from collections import deque
from enum import Enum, auto


class ProgressStatus(Enum):
    """Progress tracking status."""
    IDLE = auto()
    ACTIVE = auto()
    PAUSED = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    ERROR = auto()


@dataclass
class ProgressState:
    """
    Current progress state snapshot.
    
    Attributes:
        total_items: Total number of items to process
        completed_items: Number of items completed
        current_item: Name/description of current item being processed
        percentage: Progress percentage (0.0 to 100.0)
        eta_seconds: Estimated time remaining in seconds (None if unknown)
        elapsed_seconds: Time elapsed since start
        status: Current progress status
        error_message: Error message if status is ERROR
        items_per_second: Processing rate
    """
    total_items: int = 0
    completed_items: int = 0
    current_item: str = ""
    percentage: float = 0.0
    eta_seconds: Optional[float] = None
    elapsed_seconds: float = 0.0
    status: ProgressStatus = ProgressStatus.IDLE
    error_message: str = ""
    items_per_second: float = 0.0
    
    def is_active(self) -> bool:
        """Check if progress is currently active."""
        return self.status == ProgressStatus.ACTIVE
    
    def is_complete(self) -> bool:
        """Check if progress is complete."""
        return self.status == ProgressStatus.COMPLETED
    
    def is_cancelled(self) -> bool:
        """Check if progress was cancelled."""
        return self.status == ProgressStatus.CANCELLED
    
    def has_error(self) -> bool:
        """Check if there was an error."""
        return self.status == ProgressStatus.ERROR


class ProgressTracker:
    """
    Thread-safe progress tracker with ETA calculation.
    
    Uses a moving average of recent item completion times for accurate
    ETA estimation. Supports callbacks for real-time UI updates.
    
    Usage:
        tracker = ProgressTracker()
        
        # Start tracking
        tracker.start(total_items=100)
        
        # Update progress
        for i, item in enumerate(items):
            tracker.update(i + 1, f"Processing {item}")
            # Do work...
        
        # Complete
        tracker.complete()
        
        # Get current state
        state = tracker.get_progress()
        print(f"Progress: {state.percentage:.1f}%, ETA: {tracker.format_eta()}")
    """
    
    # Moving average window size for ETA calculation
    ETA_WINDOW_SIZE = 10
    
    def __init__(self):
        """Initialize the progress tracker."""
        self._lock = threading.RLock()
        
        # Progress state
        self._total_items = 0
        self._completed_items = 0
        self._current_item = ""
        self._status = ProgressStatus.IDLE
        self._error_message = ""
        
        # Timing
        self._start_time: Optional[float] = None
        self._last_update_time: Optional[float] = None
        self._item_times: deque = deque(maxlen=self.ETA_WINDOW_SIZE)
        
        # Callbacks
        self._callbacks: List[Callable[[ProgressState], None]] = []
        self._callback_lock = threading.Lock()
    
    def start(self, total_items: int, initial_item: str = "") -> None:
        """
        Start progress tracking.
        
        Args:
            total_items: Total number of items to process
            initial_item: Optional name of first item
        """
        with self._lock:
            self._total_items = max(1, total_items)
            self._completed_items = 0
            self._current_item = initial_item
            self._status = ProgressStatus.ACTIVE
            self._error_message = ""
            
            self._start_time = time.time()
            self._last_update_time = self._start_time
            self._item_times.clear()
        
        self._notify_callbacks()
    
    def update(self, completed: int, current_item: str = "") -> None:
        """
        Update progress.
        
        Args:
            completed: Number of items completed
            current_item: Name/description of current item
        """
        with self._lock:
            if self._status != ProgressStatus.ACTIVE:
                return
            
            now = time.time()
            
            # Track item completion time
            if completed > self._completed_items and self._last_update_time:
                items_completed = completed - self._completed_items
                time_elapsed = now - self._last_update_time
                
                # Record time per item
                if items_completed > 0:
                    time_per_item = time_elapsed / items_completed
                    self._item_times.append(time_per_item)
            
            self._completed_items = min(completed, self._total_items)
            self._current_item = current_item
            self._last_update_time = now
        
        self._notify_callbacks()
    
    def increment(self, current_item: str = "") -> None:
        """
        Increment progress by one item.
        
        Args:
            current_item: Name/description of current item
        """
        with self._lock:
            self.update(self._completed_items + 1, current_item)
    
    def set_current_item(self, item_name: str) -> None:
        """
        Set current item name without changing completion count.
        
        Args:
            item_name: Name/description of current item
        """
        with self._lock:
            self._current_item = item_name
        
        self._notify_callbacks()
    
    def pause(self) -> None:
        """Pause progress tracking."""
        with self._lock:
            if self._status == ProgressStatus.ACTIVE:
                self._status = ProgressStatus.PAUSED
        
        self._notify_callbacks()
    
    def resume(self) -> None:
        """Resume progress tracking."""
        with self._lock:
            if self._status == ProgressStatus.PAUSED:
                self._status = ProgressStatus.ACTIVE
                self._last_update_time = time.time()
        
        self._notify_callbacks()
    
    def complete(self) -> None:
        """Mark progress as complete."""
        with self._lock:
            self._completed_items = self._total_items
            self._status = ProgressStatus.COMPLETED
            self._current_item = ""
        
        self._notify_callbacks()
    
    def cancel(self) -> None:
        """Cancel progress tracking."""
        with self._lock:
            self._status = ProgressStatus.CANCELLED
        
        self._notify_callbacks()
    
    def error(self, message: str) -> None:
        """
        Set error state.
        
        Args:
            message: Error message
        """
        with self._lock:
            self._status = ProgressStatus.ERROR
            self._error_message = message
        
        self._notify_callbacks()
    
    def reset(self) -> None:
        """Reset progress tracker to initial state."""
        with self._lock:
            self._total_items = 0
            self._completed_items = 0
            self._current_item = ""
            self._status = ProgressStatus.IDLE
            self._error_message = ""
            self._start_time = None
            self._last_update_time = None
            self._item_times.clear()
        
        self._notify_callbacks()
    
    def _calculate_eta(self) -> Optional[float]:
        """
        Calculate estimated time remaining.
        
        Returns:
            ETA in seconds or None if cannot be calculated
        """
        if not self._item_times or self._completed_items == 0:
            return None
        
        remaining = self._total_items - self._completed_items
        if remaining <= 0:
            return 0.0
        
        # Use moving average of recent item times
        avg_time = sum(self._item_times) / len(self._item_times)
        return avg_time * remaining
    
    def _calculate_items_per_second(self) -> float:
        """
        Calculate processing rate.
        
        Returns:
            Items per second
        """
        if not self._start_time or self._completed_items == 0:
            return 0.0
        
        elapsed = time.time() - self._start_time
        if elapsed <= 0:
            return 0.0
        
        return self._completed_items / elapsed
    
    def get_progress(self) -> ProgressState:
        """
        Get current progress state.
        
        Returns:
            ProgressState snapshot
        """
        with self._lock:
            # Calculate percentage
            percentage = 0.0
            if self._total_items > 0:
                percentage = (self._completed_items / self._total_items) * 100.0
            
            # Calculate elapsed time
            elapsed = 0.0
            if self._start_time:
                elapsed = time.time() - self._start_time
            
            return ProgressState(
                total_items=self._total_items,
                completed_items=self._completed_items,
                current_item=self._current_item,
                percentage=percentage,
                eta_seconds=self._calculate_eta(),
                elapsed_seconds=elapsed,
                status=self._status,
                error_message=self._error_message,
                items_per_second=self._calculate_items_per_second()
            )
    
    def add_callback(self, callback: Callable[[ProgressState], None]) -> None:
        """
        Add a progress update callback.
        
        Callbacks are called on the thread that updates progress.
        For Blender UI updates, use bpy.app.timers.register() in the callback.
        
        Args:
            callback: Function to call with ProgressState on updates
        """
        with self._callback_lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)
    
    def remove_callback(self, callback: Callable[[ProgressState], None]) -> None:
        """
        Remove a progress update callback.
        
        Args:
            callback: Callback to remove
        """
        with self._callback_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)
    
    def clear_callbacks(self) -> None:
        """Remove all callbacks."""
        with self._callback_lock:
            self._callbacks.clear()
    
    def _notify_callbacks(self) -> None:
        """Notify all registered callbacks."""
        state = self.get_progress()
        
        with self._callback_lock:
            callbacks = list(self._callbacks)
        
        for callback in callbacks:
            try:
                callback(state)
            except Exception as e:
                print(f"[ProgressTracker] Callback error: {e}")
    
    def format_eta(self) -> str:
        """
        Format ETA as human-readable string.
        
        Returns:
            Formatted ETA string (e.g., "2m 30s", "Calculating...", "Complete")
        """
        state = self.get_progress()
        
        if state.status == ProgressStatus.COMPLETED:
            return "Complete"
        
        if state.status == ProgressStatus.CANCELLED:
            return "Cancelled"
        
        if state.status == ProgressStatus.ERROR:
            return "Error"
        
        eta = state.eta_seconds
        if eta is None:
            return "Calculating..."
        
        if eta <= 0:
            return "Almost done..."
        
        # Format time
        if eta < 60:
            return f"{int(eta)}s"
        elif eta < 3600:
            minutes = int(eta / 60)
            seconds = int(eta % 60)
            return f"{minutes}m {seconds}s"
        else:
            hours = int(eta / 3600)
            minutes = int((eta % 3600) / 60)
            return f"{hours}h {minutes}m"
    
    def format_elapsed(self) -> str:
        """
        Format elapsed time as human-readable string.
        
        Returns:
            Formatted elapsed time string
        """
        state = self.get_progress()
        elapsed = state.elapsed_seconds
        
        if elapsed < 60:
            return f"{int(elapsed)}s"
        elif elapsed < 3600:
            minutes = int(elapsed / 60)
            seconds = int(elapsed % 60)
            return f"{minutes}m {seconds}s"
        else:
            hours = int(elapsed / 3600)
            minutes = int((elapsed % 3600) / 60)
            return f"{hours}h {minutes}m"
    
    def format_progress(self) -> str:
        """
        Format progress as human-readable string.
        
        Returns:
            Formatted progress string (e.g., "50/100 (50.0%)")
        """
        state = self.get_progress()
        return f"{state.completed_items}/{state.total_items} ({state.percentage:.1f}%)"
    
    def format_rate(self) -> str:
        """
        Format processing rate as human-readable string.
        
        Returns:
            Formatted rate string (e.g., "2.5 items/s")
        """
        state = self.get_progress()
        rate = state.items_per_second
        
        if rate < 0.1:
            return "< 0.1 items/s"
        elif rate < 1:
            return f"{rate:.2f} items/s"
        else:
            return f"{rate:.1f} items/s"
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get a summary dictionary of current progress.
        
        Returns:
            Dictionary with formatted progress information
        """
        state = self.get_progress()
        
        return {
            'status': state.status.name,
            'progress': self.format_progress(),
            'percentage': state.percentage,
            'current_item': state.current_item,
            'elapsed': self.format_elapsed(),
            'eta': self.format_eta(),
            'rate': self.format_rate(),
            'error': state.error_message if state.has_error() else None
        }


class MultiProgressTracker:
    """
    Track progress of multiple concurrent operations.
    
    Useful for tracking parallel downloads or batch operations.
    
    Usage:
        multi_tracker = MultiProgressTracker()
        
        # Add trackers for each operation
        tracker1 = multi_tracker.create_tracker("download_1")
        tracker2 = multi_tracker.create_tracker("download_2")
        
        # Update individual trackers
        tracker1.start(100)
        tracker2.start(50)
        
        # Get overall progress
        overall = multi_tracker.get_overall_progress()
    """
    
    def __init__(self):
        """Initialize multi-progress tracker."""
        self._trackers: Dict[str, ProgressTracker] = {}
        self._lock = threading.RLock()
    
    def create_tracker(self, name: str) -> ProgressTracker:
        """
        Create a new named progress tracker.
        
        Args:
            name: Unique name for the tracker
            
        Returns:
            New ProgressTracker instance
        """
        with self._lock:
            if name in self._trackers:
                return self._trackers[name]
            
            tracker = ProgressTracker()
            self._trackers[name] = tracker
            return tracker
    
    def get_tracker(self, name: str) -> Optional[ProgressTracker]:
        """
        Get a tracker by name.
        
        Args:
            name: Tracker name
            
        Returns:
            ProgressTracker or None if not found
        """
        with self._lock:
            return self._trackers.get(name)
    
    def remove_tracker(self, name: str) -> bool:
        """
        Remove a tracker.
        
        Args:
            name: Tracker name
            
        Returns:
            True if tracker was removed
        """
        with self._lock:
            if name in self._trackers:
                del self._trackers[name]
                return True
            return False
    
    def clear(self) -> None:
        """Remove all trackers."""
        with self._lock:
            self._trackers.clear()
    
    def get_overall_progress(self) -> ProgressState:
        """
        Get combined progress of all trackers.
        
        Returns:
            ProgressState with aggregated values
        """
        with self._lock:
            if not self._trackers:
                return ProgressState()
            
            total_items = 0
            completed_items = 0
            total_elapsed = 0.0
            active_count = 0
            error_messages = []
            
            for tracker in self._trackers.values():
                state = tracker.get_progress()
                total_items += state.total_items
                completed_items += state.completed_items
                total_elapsed = max(total_elapsed, state.elapsed_seconds)
                
                if state.is_active():
                    active_count += 1
                
                if state.has_error():
                    error_messages.append(state.error_message)
            
            # Calculate overall percentage
            percentage = 0.0
            if total_items > 0:
                percentage = (completed_items / total_items) * 100.0
            
            # Determine overall status
            if error_messages:
                status = ProgressStatus.ERROR
            elif active_count > 0:
                status = ProgressStatus.ACTIVE
            elif completed_items >= total_items and total_items > 0:
                status = ProgressStatus.COMPLETED
            else:
                status = ProgressStatus.IDLE
            
            return ProgressState(
                total_items=total_items,
                completed_items=completed_items,
                current_item=f"{active_count} active operations",
                percentage=percentage,
                elapsed_seconds=total_elapsed,
                status=status,
                error_message="; ".join(error_messages) if error_messages else ""
            )
    
    def get_all_states(self) -> Dict[str, ProgressState]:
        """
        Get progress state for all trackers.
        
        Returns:
            Dictionary mapping tracker names to their states
        """
        with self._lock:
            return {
                name: tracker.get_progress()
                for name, tracker in self._trackers.items()
            }


# Global instance for main progress tracking
progress_tracker = ProgressTracker()


def get_progress_tracker() -> ProgressTracker:
    """
    Get the global progress tracker instance.
    
    Returns:
        ProgressTracker instance
    """
    return progress_tracker