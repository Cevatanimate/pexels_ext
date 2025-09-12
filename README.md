PEXELS IMAGE SEARCH - BLENDER EXTENSION
======================================

INSTALLATION:
1. Open Blender 4.2 or newer
2. Go to Edit > Preferences > Add-ons
3. Click "Install from Disk..."
4. Select the entire "pexels_ext" folder
5. Enable the "Pexels Image Search" add-on

SETUP:
1. In Add-on Preferences, enter your Pexels API key
   - Get a free key at: https://www.pexels.com/api/new/
2. Adjust settings as desired (Results per page, Cache settings, etc.)

USAGE:
1. Open 3D View and press N to show the side panel
2. Go to the "Pexels" tab
3. Enter search keywords and click "Search"
4. Browse images in the gallery
5. Select an image and click "Import as Plane" or "Import Image Only"

FEATURES:
✓ Modular code architecture for better maintainability
✓ User-friendly interface with emojis and clear sections
✓ Shows 50 results per search (up from 30)
✓ Better pagination controls
✓ Detailed image information and photographer credits
✓ Large image previews with popup scaling
✓ Advanced settings panel with cache management
✓ Proper error handling and user feedback
✓ Thumbnail caching for faster browsing
✓ Proper Blender extension format
✓ Network and file permissions declared
✓ Compatible with Blender 4.2+

PROJECT STRUCTURE:
pexels_ext/
├── __init__.py          # Main entry point and registration
├── api.py               # Pexels API communication
├── operators.py         # Blender operators (Search, Import, etc.)
├── properties.py        # Data structures and preferences
├── ui.py                # User interface panels
├── utils.py             # Utilities and helper functions
├── blender_manifest.toml # Extension metadata
└── README.md            # This file

MODULAR BENEFITS:
• Easy to maintain and extend
• Clear separation of concerns
• Better error handling and debugging
• Easier testing and development
• Cleaner code organization

All images from Pexels are free to use for commercial and personal purposes.
