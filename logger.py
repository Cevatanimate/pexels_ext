"""
Logger for Pexels Extension.

Provides comprehensive logging with multiple log levels, file logging
with rotation, console logging, and contextual information.
"""

import os
import sys
import time
import threading
import traceback
import tempfile
from datetime import datetime
from enum import IntEnum
from typing import Optional, Dict, Any, TextIO
from pathlib import Path
from collections import deque


class LogLevel(IntEnum):
    """Log level enumeration."""
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class LogRecord:
    """
    Represents a single log record.
    
    Attributes:
        timestamp: When the log was created
        level: Log level
        message: Log message
        module: Module name where log originated
        function: Function name where log originated
        line: Line number where log originated
        context: Additional context data
        exception: Exception info if any
    """
    
    def __init__(
        self,
        level: LogLevel,
        message: str,
        module: str = "",
        function: str = "",
        line: int = 0,
        context: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None
    ):
        self.timestamp = datetime.now()
        self.level = level
        self.message = message
        self.module = module
        self.function = function
        self.line = line
        self.context = context or {}
        self.exception = exception
        self.exception_traceback = ""
        
        if exception:
            self.exception_traceback = traceback.format_exc()
    
    def format(self, include_context: bool = True) -> str:
        """
        Format the log record as a string.
        
        Args:
            include_context: Whether to include context data
            
        Returns:
            Formatted log string
        """
        # Format timestamp
        ts = self.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        
        # Format level
        level_name = self.level.name
        
        # Format location
        location = ""
        if self.module or self.function:
            parts = []
            if self.module:
                parts.append(self.module)
            if self.function:
                parts.append(self.function)
            if self.line > 0:
                parts.append(str(self.line))
            location = f" [{':'.join(parts)}]"
        
        # Format message
        formatted = f"[{ts}] {level_name}{location}: {self.message}"
        
        # Add context
        if include_context and self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            formatted += f" ({context_str})"
        
        # Add exception
        if self.exception_traceback:
            formatted += f"\n{self.exception_traceback}"
        
        return formatted
    
    def format_short(self) -> str:
        """
        Format the log record as a short string for console.
        
        Returns:
            Short formatted log string
        """
        level_prefix = {
            LogLevel.DEBUG: "🔍",
            LogLevel.INFO: "ℹ️",
            LogLevel.WARNING: "⚠️",
            LogLevel.ERROR: "❌",
            LogLevel.CRITICAL: "🔥"
        }.get(self.level, "•")
        
        return f"[Pexels] {level_prefix} {self.message}"


class RotatingFileHandler:
    """
    File handler with log rotation.
    
    Rotates log files when they exceed max_bytes, keeping up to
    backup_count old files.
    """
    
    def __init__(
        self,
        filepath: str,
        max_bytes: int = 1024 * 1024,  # 1 MB
        backup_count: int = 5,
        encoding: str = 'utf-8'
    ):
        """
        Initialize rotating file handler.
        
        Args:
            filepath: Path to log file
            max_bytes: Maximum file size before rotation
            backup_count: Number of backup files to keep
            encoding: File encoding
        """
        self.filepath = filepath
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.encoding = encoding
        self._lock = threading.Lock()
        self._file: Optional[TextIO] = None
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Open file
        self._open_file()
    
    def _open_file(self) -> None:
        """Open the log file."""
        try:
            self._file = open(self.filepath, 'a', encoding=self.encoding)
        except IOError as e:
            print(f"[Logger] Failed to open log file: {e}")
            self._file = None
    
    def _should_rotate(self) -> bool:
        """Check if log file should be rotated."""
        if self._file is None:
            return False
        
        try:
            return os.path.getsize(self.filepath) >= self.max_bytes
        except OSError:
            return False
    
    def _rotate(self) -> None:
        """Rotate log files."""
        if self._file:
            self._file.close()
            self._file = None
        
        # Rotate existing backup files
        for i in range(self.backup_count - 1, 0, -1):
            src = f"{self.filepath}.{i}"
            dst = f"{self.filepath}.{i + 1}"
            
            if os.path.exists(src):
                try:
                    if os.path.exists(dst):
                        os.remove(dst)
                    os.rename(src, dst)
                except OSError:
                    pass
        
        # Rename current file to .1
        if os.path.exists(self.filepath):
            try:
                backup_path = f"{self.filepath}.1"
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                os.rename(self.filepath, backup_path)
            except OSError:
                pass
        
        # Open new file
        self._open_file()
    
    def write(self, message: str) -> None:
        """
        Write message to log file.
        
        Args:
            message: Message to write
        """
        with self._lock:
            if self._should_rotate():
                self._rotate()
            
            if self._file:
                try:
                    self._file.write(message + "\n")
                    self._file.flush()
                except IOError:
                    pass
    
    def close(self) -> None:
        """Close the log file."""
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except IOError:
                    pass
                self._file = None


class Logger:
    """
    Comprehensive logger for Pexels Extension.
    
    Features:
    - Multiple log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - File logging with rotation
    - Console logging for Blender's console
    - Contextual logging (module, function, line)
    - Thread-safe operation
    - In-memory log buffer for recent logs
    
    Usage:
        logger = Logger()
        
        # Basic logging
        logger.info("Search started", query="cats", page=1)
        logger.warning("Rate limit approaching", remaining=10)
        logger.error("Download failed", url="...", exception=e)
        
        # Debug logging (only shown if level is DEBUG)
        logger.debug("Cache hit", key="abc123")
    """
    
    _instance: Optional['Logger'] = None
    _instance_lock: threading.Lock = threading.Lock()
    
    # Default configuration
    DEFAULT_LOG_DIR = "pexels_logs"
    DEFAULT_LOG_FILE = "pexels.log"
    DEFAULT_LEVEL = LogLevel.INFO
    MAX_BUFFER_SIZE = 1000  # Keep last 1000 log entries in memory
    
    def __new__(cls) -> 'Logger':
        """Singleton pattern implementation."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance
    
    def __init__(self):
        """Initialize the logger."""
        if self._initialized:
            return
        
        self._initialized = True
        self._lock = threading.RLock()
        
        # Configuration
        self._level = self.DEFAULT_LEVEL
        self._console_enabled = True
        self._file_enabled = True
        
        # File handler
        self._file_handler: Optional[RotatingFileHandler] = None
        self._setup_file_handler()
        
        # In-memory buffer
        self._buffer: deque = deque(maxlen=self.MAX_BUFFER_SIZE)
    
    def _setup_file_handler(self) -> None:
        """Set up the file handler."""
        log_dir = self._get_log_directory()
        log_path = os.path.join(log_dir, self.DEFAULT_LOG_FILE)
        
        try:
            self._file_handler = RotatingFileHandler(
                filepath=log_path,
                max_bytes=1024 * 1024,  # 1 MB
                backup_count=5
            )
        except Exception as e:
            print(f"[Logger] Failed to set up file handler: {e}")
            self._file_handler = None
    
    def _get_log_directory(self) -> str:
        """
        Get or create the log directory.
        
        Returns:
            Path to log directory
        """
        log_dir = None
        
        # Try Blender's user directory first
        try:
            import bpy
            user_path = bpy.utils.resource_path('USER')
            log_dir = os.path.join(user_path, "logs", self.DEFAULT_LOG_DIR)
        except (ImportError, Exception):
            pass
        
        # Fall back to system temp directory
        if log_dir is None:
            log_dir = os.path.join(tempfile.gettempdir(), self.DEFAULT_LOG_DIR)
        
        # Create directory if it doesn't exist
        os.makedirs(log_dir, exist_ok=True)
        
        return log_dir
    
    def _get_caller_info(self) -> tuple:
        """
        Get caller information (module, function, line).
        
        Returns:
            Tuple of (module, function, line)
        """
        try:
            # Walk up the stack to find the actual caller
            frame = sys._getframe(3)  # Skip _get_caller_info, _log, and log method
            
            module = frame.f_globals.get('__name__', '')
            function = frame.f_code.co_name
            line = frame.f_lineno
            
            # Simplify module name
            if module.startswith('pexels_ext.'):
                module = module[11:]  # Remove 'pexels_ext.' prefix
            
            return module, function, line
        except Exception:
            return "", "", 0
    
    def _log(
        self,
        level: LogLevel,
        message: str,
        exception: Optional[Exception] = None,
        **context
    ) -> None:
        """
        Internal logging method.
        
        Args:
            level: Log level
            message: Log message
            exception: Optional exception
            **context: Additional context data
        """
        if level < self._level:
            return
        
        # Get caller info
        module, function, line = self._get_caller_info()
        
        # Create log record
        record = LogRecord(
            level=level,
            message=message,
            module=module,
            function=function,
            line=line,
            context=context,
            exception=exception
        )
        
        with self._lock:
            # Add to buffer
            self._buffer.append(record)
            
            # Write to console
            if self._console_enabled:
                self._write_console(record)
            
            # Write to file
            if self._file_enabled and self._file_handler:
                self._file_handler.write(record.format())
    
    def _write_console(self, record: LogRecord) -> None:
        """
        Write log record to console.
        
        Args:
            record: Log record to write
        """
        try:
            # Use short format for console
            message = record.format_short()
            
            # Print to appropriate stream
            if record.level >= LogLevel.ERROR:
                print(message, file=sys.stderr)
            else:
                print(message)
                
        except Exception:
            pass
    
    def debug(self, message: str, **context) -> None:
        """
        Log a debug message.
        
        Args:
            message: Log message
            **context: Additional context data
        """
        self._log(LogLevel.DEBUG, message, **context)
    
    def info(self, message: str, **context) -> None:
        """
        Log an info message.
        
        Args:
            message: Log message
            **context: Additional context data
        """
        self._log(LogLevel.INFO, message, **context)
    
    def warning(self, message: str, **context) -> None:
        """
        Log a warning message.
        
        Args:
            message: Log message
            **context: Additional context data
        """
        self._log(LogLevel.WARNING, message, **context)
    
    def error(self, message: str, exception: Optional[Exception] = None, **context) -> None:
        """
        Log an error message.
        
        Args:
            message: Log message
            exception: Optional exception that caused the error
            **context: Additional context data
        """
        self._log(LogLevel.ERROR, message, exception=exception, **context)
    
    def critical(self, message: str, exception: Optional[Exception] = None, **context) -> None:
        """
        Log a critical message.
        
        Args:
            message: Log message
            exception: Optional exception that caused the error
            **context: Additional context data
        """
        self._log(LogLevel.CRITICAL, message, exception=exception, **context)
    
    def exception(self, message: str, **context) -> None:
        """
        Log an error with the current exception.
        
        Should be called from an exception handler.
        
        Args:
            message: Log message
            **context: Additional context data
        """
        exc_info = sys.exc_info()
        exception = exc_info[1] if exc_info[1] else None
        self._log(LogLevel.ERROR, message, exception=exception, **context)
    
    def set_level(self, level: LogLevel) -> None:
        """
        Set the minimum log level.
        
        Args:
            level: Minimum log level to record
        """
        with self._lock:
            self._level = level
    
    def get_level(self) -> LogLevel:
        """
        Get the current log level.
        
        Returns:
            Current log level
        """
        return self._level
    
    def enable_console(self, enabled: bool = True) -> None:
        """
        Enable or disable console logging.
        
        Args:
            enabled: Whether to enable console logging
        """
        with self._lock:
            self._console_enabled = enabled
    
    def enable_file(self, enabled: bool = True) -> None:
        """
        Enable or disable file logging.
        
        Args:
            enabled: Whether to enable file logging
        """
        with self._lock:
            self._file_enabled = enabled
    
    def get_recent_logs(
        self,
        count: int = 100,
        min_level: Optional[LogLevel] = None
    ) -> list:
        """
        Get recent log entries.
        
        Args:
            count: Maximum number of entries to return
            min_level: Minimum log level to include
            
        Returns:
            List of LogRecord objects
        """
        with self._lock:
            logs = list(self._buffer)
            
            if min_level is not None:
                logs = [r for r in logs if r.level >= min_level]
            
            return logs[-count:]
    
    def get_log_file_path(self) -> Optional[str]:
        """
        Get the path to the current log file.
        
        Returns:
            Log file path or None if file logging is disabled
        """
        if self._file_handler:
            return self._file_handler.filepath
        return None
    
    def clear_buffer(self) -> None:
        """Clear the in-memory log buffer."""
        with self._lock:
            self._buffer.clear()
    
    def shutdown(self) -> None:
        """Shutdown the logger and close file handlers."""
        with self._lock:
            if self._file_handler:
                self._file_handler.close()
                self._file_handler = None


# Convenience functions for module-level logging
_logger: Optional[Logger] = None


def _get_logger() -> Logger:
    """Get or create the global logger instance."""
    global _logger
    if _logger is None:
        _logger = Logger()
    return _logger


def debug(message: str, **context) -> None:
    """Log a debug message."""
    _get_logger().debug(message, **context)


def info(message: str, **context) -> None:
    """Log an info message."""
    _get_logger().info(message, **context)


def warning(message: str, **context) -> None:
    """Log a warning message."""
    _get_logger().warning(message, **context)


def error(message: str, exception: Optional[Exception] = None, **context) -> None:
    """Log an error message."""
    _get_logger().error(message, exception=exception, **context)


def critical(message: str, exception: Optional[Exception] = None, **context) -> None:
    """Log a critical message."""
    _get_logger().critical(message, exception=exception, **context)


def set_level(level: LogLevel) -> None:
    """Set the minimum log level."""
    _get_logger().set_level(level)


def get_logger() -> Logger:
    """
    Get the global logger instance.
    
    Returns:
        Logger instance
    """
    return _get_logger()


# Global logger instance
logger = Logger()