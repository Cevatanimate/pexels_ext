#!/usr/bin/env python3
"""
Test script for the visual progress bar implementation.

This script tests the new progress bar components without requiring Blender.
It verifies:
1. Formatting helper functions work correctly
2. Properties are properly defined
3. UI panel class is properly structured
4. Operator classes are properly defined
"""

import sys
import os

# Add the current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_formatting_functions():
    """Test the formatting helper functions by extracting them from utils.py."""
    print("\n=== Testing Formatting Functions ===")
    
    # Read the utils.py file and extract the formatting functions
    with open('utils.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract and execute just the formatting functions
    # Find the formatting section
    start_marker = "# ============================================================================\n# Formatting Helper Functions"
    if start_marker not in content:
        print("  [!] Could not find formatting functions section")
        return False
    
    start_idx = content.find(start_marker)
    # Find the end (next section or end of file)
    end_marker = "# Register cleanup on exit"
    end_idx = content.find(end_marker, start_idx)
    
    if end_idx == -1:
        end_idx = len(content)
    
    formatting_code = content[start_idx:end_idx]
    
    # Execute the formatting functions in a local namespace
    local_ns = {}
    try:
        exec(formatting_code, local_ns)
    except Exception as e:
        print(f"  [X] Failed to execute formatting functions: {e}")
        return False
    
    format_eta = local_ns.get('format_eta')
    format_speed = local_ns.get('format_speed')
    truncate_filename = local_ns.get('truncate_filename')
    format_progress_items = local_ns.get('format_progress_items')
    format_file_size = local_ns.get('format_file_size')
    
    if not all([format_eta, format_speed, truncate_filename, format_progress_items, format_file_size]):
        print("  [X] Not all formatting functions found")
        return False
    
    # Test format_eta
    print("\nTesting format_eta:")
    test_cases = [
        (0, "Almost done"),
        (30, "30s"),
        (90, "1m 30s"),
        (3600, "1h"),
        (3660, "1h 1m"),
    ]
    all_passed = True
    for seconds, expected in test_cases:
        result = format_eta(seconds)
        passed = expected in result
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} format_eta({seconds}) = '{result}' (expected contains '{expected}')")
        all_passed &= passed
    
    # Test format_speed
    print("\nTesting format_speed:")
    speed_cases = [
        (0, "0 B/s"),
        (512, "512"),
        (1024, "KB/s"),
        (1024 * 1024, "MB/s"),
        (1024 * 1024 * 1.5, "1.5"),
    ]
    for bps, expected in speed_cases:
        result = format_speed(bps)
        passed = expected in result
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} format_speed({bps}) = '{result}' (expected contains '{expected}')")
        all_passed &= passed
    
    # Test truncate_filename
    print("\nTesting truncate_filename:")
    filename_cases = [
        ("short.jpg", 30, True),  # Should not be truncated
        ("this_is_a_very_long_filename_that_needs_truncation.jpg", 30, True),  # Should be truncated
        ("", 30, True),  # Empty string
    ]
    for filename, max_len, should_pass in filename_cases:
        result = truncate_filename(filename, max_len)
        passed = len(result) <= max_len
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} truncate_filename('{filename[:20]}...', {max_len}) = '{result}' (len={len(result)})")
        all_passed &= passed
    
    # Test format_progress_items
    print("\nTesting format_progress_items:")
    progress_cases = [
        (0, 100, "0 of 100"),
        (50, 100, "50 of 100"),
        (100, 100, "100 of 100"),
    ]
    for done, total, expected in progress_cases:
        result = format_progress_items(done, total)
        passed = expected in result
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} format_progress_items({done}, {total}) = '{result}'")
        all_passed &= passed
    
    # Test format_file_size
    print("\nTesting format_file_size:")
    size_cases = [
        (0, "0 B"),
        (512, "512"),
        (1024, "KB"),
        (1024 * 1024, "MB"),
    ]
    for size, expected in size_cases:
        result = format_file_size(size)
        passed = expected in result
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} format_file_size({size}) = '{result}'")
        all_passed &= passed
    
    if all_passed:
        print("\n[OK] All formatting function tests passed!")
    else:
        print("\n[FAIL] Some formatting function tests failed!")
    return all_passed


def test_module_structure():
    """Test that all modules have the expected structure."""
    print("\n=== Testing Module Structure ===")
    all_passed = True
    
    # Test properties.py has caching properties
    print("\nChecking properties.py:")
    with open('properties.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    required_props = [
        'caching_in_progress',
        'caching_progress',
        'caching_current_file',
        'caching_eta_seconds',
        'caching_items_done',
        'caching_items_total',
        'caching_speed_bytes',
        'caching_error_message',
    ]
    
    for prop in required_props:
        passed = prop in content
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} Property '{prop}' defined")
        all_passed &= passed
    
    # Test ui.py has progress panel
    print("\nChecking ui.py:")
    with open('ui.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    ui_requirements = [
        'PEXELS_PT_CachingProgress',
        'format_eta',
        'format_speed',
        'truncate_filename',
        '_draw_progress_bar',
        '_draw_current_file',
        '_draw_items_counter',
        '_draw_speed_indicator',
        '_draw_eta',
    ]
    
    for req in ui_requirements:
        passed = req in content
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} '{req}' present in ui.py")
        all_passed &= passed
    
    # Test operators.py has caching operators
    print("\nChecking operators.py:")
    with open('operators.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    operator_requirements = [
        'PEXELS_OT_CacheImages',
        'PEXELS_OT_CancelCaching',
        'pexels.cache_images',
        'pexels.cancel_caching',
        '_background_cache',
        '_on_cache_complete',
        '_on_cache_error',
        '_on_cache_progress',
    ]
    
    for req in operator_requirements:
        passed = req in content
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} '{req}' present in operators.py")
        all_passed &= passed
    
    # Test utils.py has formatting functions
    print("\nChecking utils.py:")
    with open('utils.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    utils_requirements = [
        'def format_eta',
        'def format_speed',
        'def truncate_filename',
        'def format_file_size',
        'def format_progress_items',
    ]
    
    for req in utils_requirements:
        passed = req in content
        status = "[OK]" if passed else "[FAIL]"
        print(f"  {status} '{req}' present in utils.py")
        all_passed &= passed
    
    if all_passed:
        print("\n[OK] All module structure tests passed!")
    else:
        print("\n[FAIL] Some module structure tests failed!")
    return all_passed


def test_operator_registration():
    """Test that operators are properly registered."""
    print("\n=== Testing Operator Registration ===")
    all_passed = True
    
    with open('operators.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check operator_classes tuple includes new operators
    if 'PEXELS_OT_CacheImages' in content and 'PEXELS_OT_CancelCaching' in content:
        # Find the operator_classes tuple
        if 'operator_classes' in content:
            # Check both are in the tuple
            tuple_start = content.find('operator_classes = (')
            if tuple_start != -1:
                tuple_end = content.find(')', tuple_start)
                tuple_content = content[tuple_start:tuple_end]
                
                cache_in_tuple = 'PEXELS_OT_CacheImages' in tuple_content
                cancel_in_tuple = 'PEXELS_OT_CancelCaching' in tuple_content
                
                status1 = "[OK]" if cache_in_tuple else "[FAIL]"
                status2 = "[OK]" if cancel_in_tuple else "[FAIL]"
                print(f"  {status1} PEXELS_OT_CacheImages in operator_classes")
                print(f"  {status2} PEXELS_OT_CancelCaching in operator_classes")
                all_passed &= cache_in_tuple and cancel_in_tuple
    
    if all_passed:
        print("\n[OK] Operator registration tests passed!")
    else:
        print("\n[FAIL] Operator registration tests failed!")
    return all_passed


def test_ui_registration():
    """Test that UI panels are properly registered."""
    print("\n=== Testing UI Registration ===")
    all_passed = True
    
    with open('ui.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check ui_classes tuple includes new panel
    if 'PEXELS_PT_CachingProgress' in content:
        tuple_start = content.find('ui_classes = (')
        if tuple_start != -1:
            tuple_end = content.find(')', tuple_start)
            tuple_content = content[tuple_start:tuple_end]
            
            panel_in_tuple = 'PEXELS_PT_CachingProgress' in tuple_content
            status = "[OK]" if panel_in_tuple else "[FAIL]"
            print(f"  {status} PEXELS_PT_CachingProgress in ui_classes")
            all_passed &= panel_in_tuple
    
    if all_passed:
        print("\n[OK] UI registration tests passed!")
    else:
        print("\n[FAIL] UI registration tests failed!")
    return all_passed


def main():
    """Run all tests."""
    print("=" * 60)
    print("Visual Progress Bar Implementation Tests")
    print("=" * 60)
    
    all_passed = True
    
    try:
        all_passed &= test_formatting_functions()
    except Exception as e:
        print(f"\n[FAIL] Formatting functions test failed: {e}")
        all_passed = False
    
    try:
        all_passed &= test_module_structure()
    except Exception as e:
        print(f"\n[FAIL] Module structure test failed: {e}")
        all_passed = False
    
    try:
        all_passed &= test_operator_registration()
    except Exception as e:
        print(f"\n[FAIL] Operator registration test failed: {e}")
        all_passed = False
    
    try:
        all_passed &= test_ui_registration()
    except Exception as e:
        print(f"\n[FAIL] UI registration test failed: {e}")
        all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("[SUCCESS] ALL TESTS PASSED!")
    else:
        print("[FAILURE] SOME TESTS FAILED")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())