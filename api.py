# SPDX-License-Identifier: GPL-3.0-or-later
"""
Pexels API handling module
"""

import json
import urllib.request
import urllib.parse
import bpy

# API Constants
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
USER_AGENT = "Blender/{major}.{minor} PexelsImageSearch/1.0".format(
    major=bpy.app.version[0], minor=bpy.app.version[1]
)


class PexelsAPIError(Exception):
    """Custom exception for Pexels API errors"""
    pass


def _http_get(url, headers=None, timeout=30):
    """Make HTTP GET request"""
    req = urllib.request.Request(url, headers=headers or {"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise PexelsAPIError("Invalid API key. Please check your Pexels API key in preferences.")
        elif e.code == 429:
            raise PexelsAPIError("Rate limit exceeded. Please try again later.")
        else:
            raise PexelsAPIError(f"HTTP Error {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        raise PexelsAPIError(f"Network error: {e.reason}")


def _http_json(url, headers=None, params=None, timeout=30):
    """Make HTTP GET request and parse JSON response"""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)

    data, response_headers = _http_get(url, headers=headers, timeout=timeout)
    try:
        return json.loads(data.decode("utf-8")), response_headers
    except json.JSONDecodeError as e:
        raise PexelsAPIError(f"Invalid JSON response: {e}")


def search_images(api_key, query, page=1, per_page=50):
    """
    Search for images on Pexels

    Args:
        api_key (str): Pexels API key
        query (str): Search query
        page (int): Page number (default: 1)
        per_page (int): Results per page (default: 50, max: 80)

    Returns:
        tuple: (search_results_dict, response_headers) - Search results with photos and metadata, plus response headers

    Raises:
        PexelsAPIError: If API request fails
    """
    if not api_key:
        raise PexelsAPIError("API key is required")

    if not query.strip():
        raise PexelsAPIError("Search query cannot be empty")

    headers = {
        "Authorization": api_key,
        "User-Agent": USER_AGENT,
    }

    params = {
        "query": query.strip(),
        "page": max(1, page),
        "per_page": min(max(1, per_page), 80)  # Clamp between 1-80
    }

    return _http_json(PEXELS_SEARCH_URL, headers=headers, params=params)


def download_image(url, headers=None):
    """
    Download image from URL

    Args:
        url (str): Image URL
        headers (dict): Optional HTTP headers

    Returns:
        bytes: Image data

    Raises:
        PexelsAPIError: If download fails
    """
    if not url:
        raise PexelsAPIError("Image URL is required")

    try:
        data, _ = _http_get(url, headers=headers or {"User-Agent": USER_AGENT})
        return data
    except Exception as e:
        raise PexelsAPIError(f"Failed to download image: {e}")
