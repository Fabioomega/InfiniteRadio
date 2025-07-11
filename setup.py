from setuptools import setup

APP = ['mac_app.py']

# List of files to include in the app bundle.
DATA_FILES = ['process_dj.py', 'icon.png']

# Options for py2app
OPTIONS = {
    'packages': ['rumps', 'psutil', 'requests'],
    
    'includes': ['pkg_resources._vendor.jaraco.text', 'pkg_resources._vendor.jaraco.functools'],
    
    'excludes': ['jaraco'],
    
    'iconfile': 'icon.icns',
    
    # This setting hides the app icon from the Dock, which is standard
    # for menu bar applications.
    'plist': {
        'LSUIElement': True,
    },
    
    # Helps the app start correctly when double-clicked in Finder.
    'argv_emulation': True,
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
    name="Infinite Radio"
)