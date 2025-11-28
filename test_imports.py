#!/usr/bin/env python3
"""
Test script to verify all imports work correctly.

This script tests that all modules can be imported without errors.
Run this outside of Blender to check for basic import issues.

Note: Modules that depend on bpy will fail outside Blender - this is expected.
"""

import sys
import os

def test_infrastructure_imports():
    """Test that infrastructure modules can be imported (no bpy dependency)."""
    print("Testing infrastructure modules (no bpy dependency)...")
    errors = []
    
    # Test logger
    try:
        import logger
        from logger import Logger, LogLevel
        print("  [OK] logger.py")
    except Exception as e:
        errors.append(f"logger.py: {e}")
        print(f"  [FAIL] logger.py: {e}")
    
    # Test progress_tracker
    try:
        import progress_tracker
        from progress_tracker import ProgressTracker, ProgressStatus
        print("  [OK] progress_tracker.py")
    except Exception as e:
        errors.append(f"progress_tracker.py: {e}")
        print(f"  [FAIL] progress_tracker.py: {e}")
    
    # Test network_manager
    try:
        import network_manager
        from network_manager import NetworkManager, NetworkStatus, OnlineAccessDisabledError, RetryConfig
        print("  [OK] network_manager.py")
    except Exception as e:
        errors.append(f"network_manager.py: {e}")
        print(f"  [FAIL] network_manager.py: {e}")
    
    # Test cache_manager
    try:
        import cache_manager
        from cache_manager import CacheManager, CacheEntry
        print("  [OK] cache_manager.py")
    except Exception as e:
        errors.append(f"cache_manager.py: {e}")
        print(f"  [FAIL] cache_manager.py: {e}")
    
    # Test task_manager
    try:
        import task_manager
        from task_manager import TaskManager, TaskPriority, TaskStatus
        print("  [OK] task_manager.py")
    except Exception as e:
        errors.append(f"task_manager.py: {e}")
        print(f"  [FAIL] task_manager.py: {e}")
    
    return errors


def test_blender_module_syntax():
    """Test that Blender-dependent modules have valid Python syntax."""
    print("\nTesting Blender-dependent modules (syntax check only)...")
    errors = []
    
    modules_to_check = ['api.py', 'operators.py', 'properties.py', 'utils.py', 'ui.py', '__init__.py']
    
    for module_name in modules_to_check:
        try:
            with open(module_name, 'r', encoding='utf-8') as f:
                source = f.read()
            compile(source, module_name, 'exec')
            print(f"  [OK] {module_name} (syntax valid)")
        except SyntaxError as e:
            errors.append(f"{module_name}: Syntax error at line {e.lineno}: {e.msg}")
            print(f"  [FAIL] {module_name}: Syntax error at line {e.lineno}: {e.msg}")
        except FileNotFoundError:
            errors.append(f"{module_name}: File not found")
            print(f"  [FAIL] {module_name}: File not found")
        except Exception as e:
            errors.append(f"{module_name}: {e}")
            print(f"  [FAIL] {module_name}: {e}")
    
    return errors


def test_infrastructure_classes():
    """Test that infrastructure classes work correctly."""
    print("\nTesting infrastructure classes functionality...")
    errors = []
    
    # Test Logger
    try:
        from logger import Logger, LogLevel
        log = Logger()
        log.set_level(LogLevel.DEBUG)
        log.debug("Test debug message")
        log.info("Test info message")
        log.warning("Test warning message")
        print("  [OK] Logger works")
    except Exception as e:
        errors.append(f"Logger: {e}")
        print(f"  [FAIL] Logger: {e}")
    
    # Test ProgressTracker
    try:
        from progress_tracker import ProgressTracker
        tracker = ProgressTracker()
        tracker.start(100, "Test")
        tracker.update(50, "Half done")
        state = tracker.get_progress()
        assert state.percentage == 50.0, f"Expected 50.0, got {state.percentage}"
        tracker.complete()
        print("  [OK] ProgressTracker works")
    except Exception as e:
        errors.append(f"ProgressTracker: {e}")
        print(f"  [FAIL] ProgressTracker: {e}")
    
    # Test RetryConfig
    try:
        from network_manager import RetryConfig
        config = RetryConfig(max_retries=5, base_delay=2.0)
        assert config.max_retries == 5
        assert config.base_delay == 2.0
        print("  [OK] RetryConfig works")
    except Exception as e:
        errors.append(f"RetryConfig: {e}")
        print(f"  [FAIL] RetryConfig: {e}")
    
    # Test TaskPriority
    try:
        from task_manager import TaskPriority, TaskStatus
        assert TaskPriority.HIGH < TaskPriority.NORMAL < TaskPriority.LOW
        print("  [OK] TaskPriority works")
    except Exception as e:
        errors.append(f"TaskPriority: {e}")
        print(f"  [FAIL] TaskPriority: {e}")
    
    # Test CacheEntry
    try:
        from cache_manager import CacheEntry
        import time
        entry = CacheEntry(
            key="test_key",
            file_path="/tmp/test.cache",
            size_bytes=100,
            created_at=time.time(),
            last_accessed=time.time(),
            expires_at=time.time() + 3600
        )
        assert not entry.is_expired()
        assert entry.key == "test_key"
        print("  [OK] CacheEntry works")
    except Exception as e:
        errors.append(f"CacheEntry: {e}")
        print(f"  [FAIL] CacheEntry: {e}")
    
    return errors


def test_cross_imports():
    """Test that infrastructure modules can import each other."""
    print("\nTesting cross-module imports...")
    errors = []
    
    # Test that logger can be imported by other modules
    try:
        from logger import get_logger
        logger = get_logger()
        logger.info("Cross-import test")
        print("  [OK] get_logger() works")
    except Exception as e:
        errors.append(f"get_logger: {e}")
        print(f"  [FAIL] get_logger: {e}")
    
    # Test that progress_tracker can be imported
    try:
        from progress_tracker import get_progress_tracker
        tracker = get_progress_tracker()
        print("  [OK] get_progress_tracker() works")
    except Exception as e:
        errors.append(f"get_progress_tracker: {e}")
        print(f"  [FAIL] get_progress_tracker: {e}")
    
    # Test that task_manager can be imported
    try:
        from task_manager import get_task_manager
        mgr = get_task_manager()
        print("  [OK] get_task_manager() works")
    except Exception as e:
        errors.append(f"get_task_manager: {e}")
        print(f"  [FAIL] get_task_manager: {e}")
    
    # Test that cache_manager can be imported
    try:
        from cache_manager import get_cache_manager
        mgr = get_cache_manager()
        print("  [OK] get_cache_manager() works")
    except Exception as e:
        errors.append(f"get_cache_manager: {e}")
        print(f"  [FAIL] get_cache_manager: {e}")
    
    # Test that network_manager can be imported
    try:
        from network_manager import get_network_manager
        mgr = get_network_manager()
        print("  [OK] get_network_manager() works")
    except Exception as e:
        errors.append(f"get_network_manager: {e}")
        print(f"  [FAIL] get_network_manager: {e}")
    
    return errors


if __name__ == "__main__":
    print("=" * 60)
    print("Pexels Extension Import Test")
    print("=" * 60)
    
    # Change to the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(script_dir)
    
    print(f"Working directory: {os.getcwd()}")
    print()
    
    all_errors = []
    
    # Run tests
    all_errors.extend(test_infrastructure_imports())
    all_errors.extend(test_blender_module_syntax())
    all_errors.extend(test_infrastructure_classes())
    all_errors.extend(test_cross_imports())
    
    # Summary
    print("\n" + "=" * 60)
    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s) found")
        for error in all_errors:
            print(f"  - {error}")
        sys.exit(1)
    else:
        print("SUCCESS: All tests passed!")
        print("\nNote: Blender-dependent modules (api.py, operators.py, etc.)")
        print("      were only syntax-checked. Full testing requires Blender.")
        sys.exit(0)