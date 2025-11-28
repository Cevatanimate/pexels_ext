# SPDX-License-Identifier: GPL-3.0-or-later
"""
Pexels API handling module.

Provides functions for searching and downloading images from the Pexels API.
Integrates with NetworkManager for connectivity checking, retry logic, and
online access preference checking.
"""

import json
import urllib.parse
import threading
from typing import Optional, Dict, Any, Tuple

import bpy

from .network_manager import (
    network_manager,
    NetworkManager,
    OnlineAccessDisabledError,
    NetworkError,
    ConnectivityError,
    HTTPError,
    TimeoutError as NetworkTimeoutError,
    RetryConfig
)
from .logger import logger, LogLevel


# API Constants
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
USER_AGENT = "Blender/{major}.{minor} PexelsImageSearch/1.0".format(
    major=bpy.app.version[0], minor=bpy.app.version[1]
)

# Default timeout for API requests
DEFAULT_TIMEOUT = 30.0


class PexelsAPIError(Exception):
    """Base exception for Pexels API errors."""
    pass


class PexelsAuthError(PexelsAPIError):
    """Authentication error - invalid API key."""
    pass


class PexelsRateLimitError(PexelsAPIError):
    """Rate limit exceeded."""
    def __init__(self, reset_time: int = 0, message: str = "Rate limit exceeded"):
        self.reset_time = reset_time
        super().__init__(message)


class PexelsNetworkError(PexelsAPIError):
    """Network connectivity error."""
    pass


class PexelsCancellationError(PexelsAPIError):
    """Operation was cancelled."""
    pass


def get_network_manager() -> NetworkManager:
    """
    Get the global network manager instance.
    
    Returns:
        NetworkManager instance
    """
    return network_manager


def check_online_access() -> bool:
    """
    Check if online access is enabled in Blender preferences.
    
    Returns:
        True if online access is enabled, False otherwise
    """
    return network_manager.is_online_access_enabled()


def get_online_access_disabled_message() -> str:
    """
    Get the user-facing message when online access is disabled.
    
    Returns:
        Formatted message string
    """
    return (
        "Operation cancelled: Online access is disabled in preferences.\n"
        "To enable online access:\n"
        "1. Go to Edit > Preferences > System\n"
        "2. Enable 'Online Access' under Network\n"
        "3. Restart Blender or re-enable the addon"
    )


def search_images(
    api_key: str,
    query: str,
    page: int = 1,
    per_page: int = 50,
    timeout: float = DEFAULT_TIMEOUT,
    cancellation_token: Optional[threading.Event] = None,
    progress_callback: Optional[callable] = None
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Search for images on Pexels.

    Args:
        api_key: Pexels API key
        query: Search query
        page: Page number (default: 1)
        per_page: Results per page (default: 50, max: 80)
        timeout: Request timeout in seconds
        cancellation_token: Event to signal cancellation
        progress_callback: Callback for progress updates (progress: float, message: str)

    Returns:
        Tuple of (search_results_dict, response_headers)

    Raises:
        OnlineAccessDisabledError: If online access is disabled in Blender preferences
        PexelsAuthError: If API key is invalid
        PexelsRateLimitError: If rate limit is exceeded
        PexelsNetworkError: If network error occurs
        PexelsCancellationError: If operation is cancelled
        PexelsAPIError: For other API errors
    """
    # Validate inputs
    if not api_key:
        logger.error("API key is required for search")
        raise PexelsAPIError("API key is required")

    if not query or not query.strip():
        logger.warning("Empty search query provided")
        raise PexelsAPIError("Search query cannot be empty")

    # Check online access preference
    if not network_manager.is_online_access_enabled():
        logger.warning("Online access is disabled in Blender preferences")
        raise OnlineAccessDisabledError(get_online_access_disabled_message())

    # Check cancellation
    if cancellation_token and cancellation_token.is_set():
        logger.info("Search cancelled before starting")
        raise PexelsCancellationError("Search cancelled")

    # Build request URL
    params = {
        "query": query.strip(),
        "page": max(1, page),
        "per_page": min(max(1, per_page), 80)  # Clamp between 1-80
    }
    url = f"{PEXELS_SEARCH_URL}?{urllib.parse.urlencode(params)}"

    # Build headers
    headers = {
        "Authorization": api_key,
        "User-Agent": USER_AGENT,
    }

    logger.info("Starting Pexels search", query=query, page=page, per_page=per_page)

    try:
        # Report progress
        if progress_callback:
            progress_callback(0.1, "Connecting to Pexels API...")

        # Make request with retry
        retry_config = RetryConfig(
            max_retries=3,
            base_delay=1.0,
            max_delay=10.0
        )

        data, response_headers = network_manager.download_with_retry(
            url=url,
            headers=headers,
            timeout=timeout,
            retry_config=retry_config,
            cancellation_token=cancellation_token,
            on_progress=progress_callback
        )

        # Parse JSON response
        try:
            results = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error("Invalid JSON response from Pexels API", exception=e)
            raise PexelsAPIError(f"Invalid JSON response: {e}")

        # Log success
        total_results = results.get("total_results", 0)
        photos_count = len(results.get("photos", []))
        logger.info(
            "Search completed successfully",
            query=query,
            total_results=total_results,
            photos_returned=photos_count
        )

        return results, response_headers

    except OnlineAccessDisabledError:
        raise

    except InterruptedError:
        logger.info("Search cancelled by user")
        raise PexelsCancellationError("Search cancelled")

    except HTTPError as e:
        if e.code == 401:
            logger.error("Invalid API key", http_code=e.code)
            raise PexelsAuthError("Invalid API key. Please check your Pexels API key in preferences.")
        elif e.code == 429:
            logger.warning("Rate limit exceeded", http_code=e.code)
            raise PexelsRateLimitError(message="Rate limit exceeded. Please try again later.")
        else:
            logger.error("HTTP error during search", http_code=e.code, reason=e.reason)
            raise PexelsAPIError(f"HTTP Error {e.code}: {e.reason}")

    except ConnectivityError as e:
        logger.error("Network connectivity error", exception=e)
        raise PexelsNetworkError(f"Network error: {e}")

    except NetworkTimeoutError as e:
        logger.error("Request timeout", exception=e)
        raise PexelsNetworkError(f"Request timed out: {e}")

    except NetworkError as e:
        logger.error("Network error during search", exception=e)
        raise PexelsNetworkError(f"Network error: {e}")

    except PexelsAPIError:
        raise

    except Exception as e:
        logger.error("Unexpected error during search", exception=e)
        raise PexelsAPIError(f"Search failed: {e}")


def download_image(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 60.0,
    cancellation_token: Optional[threading.Event] = None,
    progress_callback: Optional[callable] = None
) -> bytes:
    """
    Download image from URL.

    Args:
        url: Image URL
        headers: Optional HTTP headers
        timeout: Request timeout in seconds
        cancellation_token: Event to signal cancellation
        progress_callback: Callback for progress updates

    Returns:
        Image data as bytes

    Raises:
        OnlineAccessDisabledError: If online access is disabled
        PexelsNetworkError: If download fails
        PexelsCancellationError: If operation is cancelled
        PexelsAPIError: For other errors
    """
    if not url:
        logger.error("Image URL is required for download")
        raise PexelsAPIError("Image URL is required")

    # Check online access preference
    if not network_manager.is_online_access_enabled():
        logger.warning("Online access is disabled - cannot download image")
        raise OnlineAccessDisabledError(get_online_access_disabled_message())

    # Check cancellation
    if cancellation_token and cancellation_token.is_set():
        logger.info("Download cancelled before starting")
        raise PexelsCancellationError("Download cancelled")

    # Build headers
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)

    logger.debug("Starting image download", url=url[:100])

    try:
        # Download with progress reporting
        def on_download_progress(progress):
            if progress_callback:
                progress_callback(
                    progress.percentage / 100.0,
                    f"Downloaded {progress.downloaded_bytes / 1024:.1f} KB"
                )

        data = network_manager.download(
            url=url,
            headers=req_headers,
            timeout=timeout,
            cancellation_token=cancellation_token,
            on_progress=on_download_progress
        )

        logger.debug("Image download completed", size_bytes=len(data))
        return data

    except OnlineAccessDisabledError:
        raise

    except InterruptedError:
        logger.info("Download cancelled by user")
        raise PexelsCancellationError("Download cancelled")

    except HTTPError as e:
        logger.error("HTTP error during download", http_code=e.code, url=url[:100])
        raise PexelsNetworkError(f"HTTP Error {e.code}: {e.reason}")

    except (ConnectivityError, NetworkTimeoutError, NetworkError) as e:
        logger.error("Network error during download", exception=e, url=url[:100])
        raise PexelsNetworkError(f"Download failed: {e}")

    except PexelsAPIError:
        raise

    except Exception as e:
        logger.error("Unexpected error during download", exception=e, url=url[:100])
        raise PexelsAPIError(f"Failed to download image: {e}")


def check_api_connectivity() -> bool:
    """
    Check if Pexels API is reachable.
    
    Returns:
        True if API is reachable, False otherwise
    """
    return network_manager.is_online()


def get_api_status() -> str:
    """
    Get a human-readable API status message.
    
    Returns:
        Status message string
    """
    return network_manager.get_status_message()
