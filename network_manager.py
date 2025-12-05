"""
Network Manager for Pexels Extension.

Provides network utilities including connectivity checking, retry logic
with exponential backoff, and Blender online access preference checking.
"""

import urllib.request
import urllib.error
import socket
import time
import threading
import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Tuple, Dict, Any, Callable


class NetworkStatus(Enum):
    """Network connectivity status."""
    ONLINE = auto()
    OFFLINE = auto()
    UNKNOWN = auto()


class OnlineAccessDisabledError(Exception):
    """
    Raised when online access is disabled in Blender preferences.
    
    This is a user preference, not a network error.
    """
    def __init__(self, message: str = "Online access is disabled in Blender preferences"):
        self.message = message
        super().__init__(self.message)


class NetworkError(Exception):
    """Base exception for network errors."""
    pass


class ConnectivityError(NetworkError):
    """Raised when there is no network connectivity."""
    pass


class TimeoutError(NetworkError):
    """Raised when a request times out."""
    pass


class HTTPError(NetworkError):
    """
    Raised for HTTP errors.
    
    Attributes:
        code: HTTP status code
        reason: HTTP reason phrase
    """
    def __init__(self, code: int, reason: str, message: str = ""):
        self.code = code
        self.reason = reason
        self.message = message or f"HTTP Error {code}: {reason}"
        super().__init__(self.message)


@dataclass
class RetryConfig:
    """
    Configuration for retry logic with exponential backoff.
    
    Attributes:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential backoff
        jitter: Random jitter factor (0.0 to 1.0)
        retryable_status_codes: HTTP status codes that should trigger retry
    """
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: float = 0.1
    retryable_status_codes: Tuple[int, ...] = field(
        default_factory=lambda: (429, 500, 502, 503, 504)
    )


@dataclass
class DownloadProgress:
    """
    Download progress information.
    
    Attributes:
        downloaded_bytes: Bytes downloaded so far
        total_bytes: Total bytes to download (0 if unknown)
        percentage: Download percentage (0.0 to 100.0)
        speed_bps: Download speed in bytes per second
    """
    downloaded_bytes: int = 0
    total_bytes: int = 0
    percentage: float = 0.0
    speed_bps: float = 0.0


class NetworkManager:
    """
    Network utilities with connectivity checking and retry logic.
    
    Implements singleton pattern for global access.
    
    CRITICAL: All network operations check Blender's online access preference
    before making any requests. If disabled, operations raise OnlineAccessDisabledError.
    
    Features:
    - Online access preference checking
    - Connectivity verification
    - Retry with exponential backoff
    - Download with progress reporting
    - Request timeout handling
    
    Usage:
        network_manager = NetworkManager()
        
        # Check if online access is enabled
        if network_manager.is_online_access_enabled():
            # Make request with retry
            data, headers = network_manager.download_with_retry(
                url="https://api.pexels.com/v1/search",
                headers={"Authorization": "your-api-key"}
            )
    """
    
    _instance: Optional['NetworkManager'] = None
    _instance_lock: threading.Lock = threading.Lock()
    
    # Connectivity check endpoints (in order of preference)
    CHECK_ENDPOINTS = [
        ("api.pexels.com", 443),
        ("www.google.com", 443),
        ("1.1.1.1", 443),
    ]
    
    # Default configuration
    DEFAULT_TIMEOUT = 30.0  # seconds
    CONNECTIVITY_CHECK_INTERVAL = 30.0  # seconds
    CONNECTIVITY_CHECK_TIMEOUT = 5.0  # seconds
    
    def __new__(cls) -> 'NetworkManager':
        """Singleton pattern implementation."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance
    
    def __init__(self):
        """Initialize the network manager."""
        if self._initialized:
            return
        
        self._initialized = True
        
        # Connectivity status
        self._status = NetworkStatus.UNKNOWN
        self._last_check_time = 0.0
        self._status_lock = threading.Lock()
        
        # User agent for requests
        self._user_agent = "PexelsBlenderExtension/1.0"
    
    def is_online_access_enabled(self) -> bool:
        """
        Check if Blender's Online Access preference is enabled.
        
        This MUST be checked before ANY network operation.
        
        Returns:
            True if online access is enabled, False otherwise
        """
        try:
            import bpy
            
            # Check if we have access to preferences
            if not hasattr(bpy, 'context') or bpy.context is None:
                # Context not available, assume enabled
                return True
            
            prefs = getattr(bpy.context, 'preferences', None)
            if prefs is None:
                return True
            
            system = getattr(prefs, 'system', None)
            if system is None:
                return True
            
            # Blender 4.2+ has use_online_access preference
            if hasattr(system, 'use_online_access'):
                return system.use_online_access
            
            # Older versions or preference not found - default to enabled
            return True
            
        except Exception:
            # If we can't check, assume enabled
            return True
    
    def _ensure_online_access(self) -> None:
        """
        Ensure online access is enabled.
        
        Raises:
            OnlineAccessDisabledError: If online access is disabled
        """
        if not self.is_online_access_enabled():
            raise OnlineAccessDisabledError(
                "Online access is disabled in Blender preferences. "
                "Enable it in Edit > Preferences > System > Network to use this feature."
            )
    
    def check_connectivity(self, force: bool = False) -> NetworkStatus:
        """
        Check network connectivity.
        
        Args:
            force: Force check even if recently checked
            
        Returns:
            NetworkStatus indicating connectivity state
        """
        with self._status_lock:
            # Return cached status if recent
            current_time = time.time()
            if not force and (current_time - self._last_check_time) < self.CONNECTIVITY_CHECK_INTERVAL:
                return self._status
            
            # Check online access preference first
            if not self.is_online_access_enabled():
                self._status = NetworkStatus.OFFLINE
                self._last_check_time = current_time
                return self._status
            
            # Try to connect to check endpoints
            for host, port in self.CHECK_ENDPOINTS:
                try:
                    sock = socket.create_connection(
                        (host, port),
                        timeout=self.CONNECTIVITY_CHECK_TIMEOUT
                    )
                    sock.close()
                    self._status = NetworkStatus.ONLINE
                    self._last_check_time = current_time
                    return self._status
                except (socket.timeout, socket.error, OSError):
                    continue
            
            self._status = NetworkStatus.OFFLINE
            self._last_check_time = current_time
            return self._status
    
    def is_online(self) -> bool:
        """
        Quick check if network is available.
        
        Returns:
            True if online, False otherwise
        """
        return self.check_connectivity() == NetworkStatus.ONLINE
    
    def _calculate_delay(self, attempt: int, config: RetryConfig) -> float:
        """
        Calculate delay for retry with exponential backoff and jitter.
        
        Args:
            attempt: Current attempt number (0-based)
            config: Retry configuration
            
        Returns:
            Delay in seconds
        """
        delay = min(
            config.base_delay * (config.exponential_base ** attempt),
            config.max_delay
        )
        
        # Add jitter
        if config.jitter > 0:
            jitter_range = delay * config.jitter
            delay += random.uniform(-jitter_range, jitter_range)
        
        return max(0.0, delay)
    
    def _sleep_with_cancellation(
        self,
        duration: float,
        cancellation_token: Optional[threading.Event]
    ) -> bool:
        """
        Sleep for duration with cancellation support.
        
        Args:
            duration: Sleep duration in seconds
            cancellation_token: Event to check for cancellation
            
        Returns:
            True if sleep completed, False if cancelled
        """
        if cancellation_token is None:
            time.sleep(duration)
            return True
        
        # Sleep in small increments to check for cancellation
        end_time = time.time() + duration
        while time.time() < end_time:
            if cancellation_token.is_set():
                return False
            time.sleep(min(0.1, end_time - time.time()))
        
        return True
    
    def download(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        cancellation_token: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[DownloadProgress], None]] = None
    ) -> bytes:
        """
        Download data from URL with progress reporting.
        
        Args:
            url: URL to download from
            headers: Optional HTTP headers
            timeout: Request timeout in seconds
            cancellation_token: Event to signal cancellation
            on_progress: Callback for progress updates
            
        Returns:
            Downloaded data as bytes
            
        Raises:
            OnlineAccessDisabledError: If online access is disabled
            ConnectivityError: If no network connectivity
            HTTPError: For HTTP errors
            TimeoutError: If request times out
            InterruptedError: If cancelled
        """
        # Check online access preference
        self._ensure_online_access()
        
        # Check connectivity
        if not self.is_online():
            raise ConnectivityError("No network connectivity. Check your internet connection.")
        
        # Check cancellation
        if cancellation_token and cancellation_token.is_set():
            raise InterruptedError("Download cancelled")
        
        # Prepare request
        req_headers = {"User-Agent": self._user_agent}
        if headers:
            req_headers.update(headers)
        
        req = urllib.request.Request(url, headers=req_headers)
        
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                # Get content length if available
                total_size = int(response.headers.get('Content-Length', 0))
                
                # Download with progress
                chunks = []
                downloaded = 0
                start_time = time.time()
                
                while True:
                    # Check cancellation
                    if cancellation_token and cancellation_token.is_set():
                        raise InterruptedError("Download cancelled")
                    
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    
                    # Report progress
                    if on_progress:
                        elapsed = time.time() - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        percentage = (downloaded / total_size * 100) if total_size > 0 else 0
                        
                        progress = DownloadProgress(
                            downloaded_bytes=downloaded,
                            total_bytes=total_size,
                            percentage=percentage,
                            speed_bps=speed
                        )
                        on_progress(progress)
                
                return b''.join(chunks)
                
        except urllib.error.HTTPError as e:
            raise HTTPError(e.code, e.reason)
        except urllib.error.URLError as e:
            if isinstance(e.reason, socket.timeout):
                raise TimeoutError(f"Request timed out after {timeout} seconds")
            raise ConnectivityError(f"Network error: {e.reason}")
        except socket.timeout:
            raise TimeoutError(f"Request timed out after {timeout} seconds")
    
    def download_with_retry(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_config: Optional[RetryConfig] = None,
        cancellation_token: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[float, str], None]] = None
    ) -> Tuple[bytes, Dict[str, str]]:
        """
        Download data with retry logic and exponential backoff.
        
        Args:
            url: URL to download from
            headers: Optional HTTP headers
            timeout: Request timeout in seconds
            retry_config: Retry configuration (uses defaults if None)
            cancellation_token: Event to signal cancellation
            on_progress: Callback for progress updates (progress: float, message: str)
            
        Returns:
            Tuple of (data, response_headers)
            
        Raises:
            OnlineAccessDisabledError: If online access is disabled
            ConnectivityError: If no network connectivity
            HTTPError: For non-retryable HTTP errors
            TimeoutError: If all retries exhausted due to timeouts
            InterruptedError: If cancelled
        """
        # Check online access preference
        self._ensure_online_access()
        
        config = retry_config or RetryConfig()
        last_error: Optional[Exception] = None
        
        for attempt in range(config.max_retries + 1):
            # Check cancellation
            if cancellation_token and cancellation_token.is_set():
                raise InterruptedError("Request cancelled")
            
            # Check connectivity
            if not self.is_online():
                raise ConnectivityError("No network connectivity. Check your internet connection.")
            
            try:
                # Report attempt
                if on_progress:
                    progress = attempt / (config.max_retries + 1)
                    message = f"Attempt {attempt + 1}/{config.max_retries + 1}"
                    on_progress(progress, message)
                
                # Prepare request
                req_headers = {"User-Agent": self._user_agent}
                if headers:
                    req_headers.update(headers)
                
                req = urllib.request.Request(url, headers=req_headers)
                
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    data = response.read()
                    response_headers = dict(response.headers)
                    return data, response_headers
                    
            except urllib.error.HTTPError as e:
                # Don't retry on client errors (4xx) except retryable ones
                if e.code not in config.retryable_status_codes:
                    raise HTTPError(e.code, e.reason)
                last_error = HTTPError(e.code, e.reason)
                
            except urllib.error.URLError as e:
                if isinstance(e.reason, socket.timeout):
                    last_error = TimeoutError(f"Request timed out after {timeout} seconds")
                else:
                    last_error = ConnectivityError(f"Network error: {e.reason}")
                    
            except socket.timeout:
                last_error = TimeoutError(f"Request timed out after {timeout} seconds")
            
            # Calculate and apply delay before retry
            if attempt < config.max_retries:
                delay = self._calculate_delay(attempt, config)
                
                if on_progress:
                    on_progress(
                        attempt / (config.max_retries + 1),
                        f"Retrying in {delay:.1f}s..."
                    )
                
                # Sleep with cancellation support
                if not self._sleep_with_cancellation(delay, cancellation_token):
                    raise InterruptedError("Request cancelled")
        
        # All retries exhausted
        if last_error:
            raise last_error
        raise NetworkError("Request failed after all retries")
    
    def request_json(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_config: Optional[RetryConfig] = None,
        cancellation_token: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[float, str], None]] = None
    ) -> Tuple[Any, Dict[str, str]]:
        """
        Make a request and parse JSON response.
        
        Args:
            url: URL to request
            headers: Optional HTTP headers
            timeout: Request timeout in seconds
            retry_config: Retry configuration
            cancellation_token: Event to signal cancellation
            on_progress: Callback for progress updates
            
        Returns:
            Tuple of (parsed_json, response_headers)
            
        Raises:
            OnlineAccessDisabledError: If online access is disabled
            ConnectivityError: If no network connectivity
            HTTPError: For HTTP errors
            ValueError: If response is not valid JSON
        """
        import json
        
        data, headers_out = self.download_with_retry(
            url=url,
            headers=headers,
            timeout=timeout,
            retry_config=retry_config,
            cancellation_token=cancellation_token,
            on_progress=on_progress
        )
        
        try:
            parsed = json.loads(data.decode('utf-8'))
            return parsed, headers_out
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid JSON response: {e}")
    
    def get_status_message(self) -> str:
        """
        Get a human-readable status message.
        
        Returns:
            Status message string
        """
        if not self.is_online_access_enabled():
            return "Online access is disabled in Blender preferences"
        
        status = self.check_connectivity()
        if status == NetworkStatus.ONLINE:
            return "Connected"
        elif status == NetworkStatus.OFFLINE:
            return "No internet connection"
        else:
            return "Connection status unknown"


# Global instance
network_manager = None


def get_network_manager() -> NetworkManager:
    """
    Get the global network manager instance.
    
    Returns:
        NetworkManager instance
    """
    global network_manager
    if network_manager is None:
        network_manager = NetworkManager()
    return network_manager