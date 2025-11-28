# 🖼️ Pexels Image Search - Blender Extension

> **Search, preview, and import high-quality images from Pexels directly into Blender**

[![Blender](https://img.shields.io/badge/Blender-4.2%2B-orange.svg)](https://www.blender.org/)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Pexels API](https://img.shields.io/badge/Powered%20by-Pexels%20API-green.svg)](https://www.pexels.com/api/)

## ✨ Features

- 🔍 **Powerful Search** - Search through millions of high-quality images
- 🖼️ **Large Previews** - Browse images with high-resolution previews  
- ⚡ **Fast Import** - One-click import as textured planes or standalone images
- 🎨 **Smart Materials** - Automatically creates materials with proper UV mapping
- 📊 **Pagination** - Navigate through multiple pages of results
- 💾 **Thumbnail Caching** - Faster browsing with cached previews
- 🛠️ **Advanced Settings** - Customizable results per page and import options
- 🆓 **Free Images** - All Pexels images are free for commercial use
- 📱 **User-Friendly UI** - Clean interface with helpful guidance

## 📦 Installation

### Prerequisites
- **Blender 4.2** or newer
- **Internet connection** for API access
- **Free Pexels API key** ([Get one here](https://www.pexels.com/api/))

### Install Steps
1. **Download** this extension folder (`pexels_ext`)
2. **Open Blender** and go to `Edit > Preferences > Add-ons`
3. **Click** "Install from Disk..."
4. **Select** the entire `pexels_ext` folder
5. **Enable** the "Pexels Image Search" add-on
6. **Configure** your API key in the add-on preferences

## ⚙️ Setup

### 1. Get API Key
1. Visit [https://www.pexels.com/api/](https://www.pexels.com/api/)
2. Create a free account or log in
3. Copy your API key

### 2. Configure Extension
1. In Blender preferences, find "Pexels Image Search"
2. Paste your API key in the "Pexels API Key" field
3. Adjust settings as desired:
   - **Results per Page**: 1-80 images (default: 50)
   - **Cache Thumbnails**: Enable for faster browsing
   - **Default Plane Size**: Size for imported planes

## 🚀 Usage

### Basic Workflow
1. **Open N-Panel** - Press `N` in 3D View to show side panel
2. **Go to Pexels Tab** - Click on the "Pexels" tab
3. **Enter Keywords** - Type search terms (e.g., "nature", "architecture")
4. **Click Search** - Browse through image results
5. **Select Image** - Click on any image thumbnail
6. **Import** - Choose "Import as Plane" or "Import Image Only"

### Search Tips
- 🎯 **Be specific** - "mountain sunset" vs "nature"
- 🔄 **Try variations** - "car", "automobile", "vehicle"
- 📄 **Use pages** - Navigate through multiple result pages
- 🎨 **Categories** - Try "abstract", "textures", "backgrounds"

### Import Options
- **Import as Plane** - Creates a mesh plane with the image as texture
- **Import Image Only** - Adds image to Blender's image library

## 🔧 Advanced Features

### Settings Panel
Access advanced options in the collapsible "Settings" panel:
- 📊 API key status
- ⚙️ Quick preference adjustments
- 🗂️ Cache management tools

### Error Handling
- 🔐 **API Key Validation** - Clear guidance for setup
- 🌐 **Network Error Handling** - Helpful error messages
- 📊 **Rate Limit Management** - Graceful handling of API limits

### Performance
- 💾 **Smart Caching** - Thumbnails cached for faster browsing
- ⚡ **Optimized Requests** - Efficient API usage
- 🎛️ **Resource Management** - Proper cleanup and memory handling

## 🆘 Troubleshooting

### Common Issues

**❌ "API Key Required" Error**
- Ensure you've set your API key in Add-on Preferences
- Verify the key is correct (get a new one if needed)

**❌ "Search Failed" Error**
- Check your internet connection
- Verify API key is valid
- Try simpler search terms

**❌ "No Images Found"**
- Try different or broader keywords
- Check spelling of search terms
- Some very specific terms may have no results

**❌ Import Fails**
- Ensure stable internet connection
- Try importing as "Image Only" instead of plane
- Check Blender console for detailed error messages

### Getting Help
1. Check the add-on preferences for guidance
2. Try clearing cache in the Settings panel
3. Restart Blender if issues persist
4. Verify your API key is still valid

## 📄 License & Credits

- **Extension License**: GPL-3.0-or-later
- **Images**: All Pexels images are free for commercial and personal use
- **API**: Powered by [Pexels API](https://www.pexels.com/api/)
- **Platform**: Built for [Blender](https://www.blender.org/)

## 🔄 Version History

### v1.0.3
- 🔧 **Better Caching** and control
- 🎨 **Better preview system**
- 📊 **Improved Download Feedback**

---

**Made with ❤️ for the Blender community**

*All images from Pexels are free to use for commercial and personal purposes with no attribution required.*
