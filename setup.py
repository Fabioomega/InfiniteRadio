from setuptools import setup

APP = ['mac_app.py']

# List of files to include in the app bundle.
DATA_FILES = ['process_dj.py', 'llm_dj.py', 'icon.png']

# Options for py2app
OPTIONS = {
    'packages': ['rumps', 'psutil', 'requests', 'mss', 'PIL', 'openai', 'httpx', 'ssl', 'certifi', 'Quartz'],
    
    'includes': [
        'pkg_resources._vendor.jaraco.text', 
        'pkg_resources._vendor.jaraco.functools',
        'certifi',
        'ssl'
    ],
    
    'excludes': ['jaraco'],
    
    'iconfile': 'icon.icns',
    
    # This setting hides the app icon from the Dock, which is standard
    # for menu bar applications.
    'plist': {
        'LSUIElement': True,
        'NSAppTransportSecurity': {
            'NSAllowsArbitraryLoads': True
        },
        'NSScreenCaptureUsageDescription': 'Infinite Radio needs to see your screen to use the LLM music genre feature.',
        'CFBundleIdentifier': 'com.infiniteradio.app',
        'CFBundleDisplayName': 'Infinite Radio',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0'
    },
    
    # Helps the app start correctly when double-clicked in Finder.
    'argv_emulation': True,
    
    # Include SSL certificates
    'resources': ['icon.png'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
    name="Infinite Radio"
)