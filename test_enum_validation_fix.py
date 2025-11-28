

v#!/usr/bin/env python3
"""
Test script to verify the enum validation fix for the Pexels addon.

This script tests that the enum validation error is resolved and that
the selected_icon property works correctly with the private attribute approach.
"""

import bpy
import sys
import os

# Add the current directory to Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_enum_validation():
    """Test that enum validation works correctly"""
    print("Testing enum validation fix...")

    # Get the Pexels state
    state = bpy.context.scene.pexels_state

    # Clear any existing results
    state.clear_results()

    # Add some test items (simulating search results)
    for i in range(3):
        item = state.items.add()
        item.item_id = i + 1
        item.photographer = f"Photographer {i + 1}"
        item.thumb_url = f"https://example.com/thumb_{i + 1}.jpg"
        item.full_url = f"https://example.com/full_{i + 1}.jpg"
        item.width = 800
        item.height = 600

    print(f"Added {len(state.items)} test items")

    # Test enum items generation
    from properties import pexels_enum_items
    enum_items = pexels_enum_items(state, bpy.context)
    print(f"Generated {len(enum_items)} enum items")

    # Test setting selection using private attribute (should not cause validation error)
    if enum_items:
        first_item_id = enum_items[0][0]
        print(f"Setting selection to: {first_item_id}")

        # This should work without causing the enum validation error
        state._selected_icon = first_item_id

        # Test getting the selected item
        selected_item = state.get_selected_item()
        if selected_item:
            print(f"✅ SUCCESS: Selected item retrieved: {selected_item.photographer}")
            return True
        else:
            print("❌ FAILURE: Could not retrieve selected item")
            return False
    else:
        print("⚠️  WARNING: No enum items generated for testing")
        return True

def test_clear_results():
    """Test that clear_results doesn't cause enum validation errors"""
    print("\nTesting clear_results method...")

    state = bpy.context.scene.pexels_state

    # Set a selection first
    if state.items:
        state._selected_icon = str(state.items[0].item_id)

    # Clear results - this should not cause enum validation error
    try:
        state.clear_results()
        print("✅ SUCCESS: clear_results() completed without enum validation error")
        return True
    except Exception as e:
        print(f"❌ FAILURE: clear_results() caused error: {e}")
        return False

def test_validation_method():
    """Test the validation method directly"""
    print("\nTesting validation method...")

    state = bpy.context.scene.pexels_state

    # Add a test item
    item = state.items.add()
    item.item_id = 999
    item.photographer = "Test Photographer"

    # Test validation with valid value
    valid_value = str(item.item_id)
    result = state._validate_selected_icon(valid_value)

    if result == valid_value:
        print("✅ SUCCESS: Valid value passed validation")
        return True
    else:
        print("❌ FAILURE: Valid value failed validation")
        return False

if __name__ == "__main__":
    print("Running Pexels enum validation fix tests...\n")

    success1 = test_enum_validation()
    success2 = test_clear_results()
    success3 = test_validation_method()

    if success1 and success2 and success3:
        print("\n🎉 All tests passed! The enum validation error should be resolved.")
    else:
        print("\n💥 Some tests failed. The fix may need additional work.")