# top_process_dj_refined.py

import time
import sys
import psutil
import requests
import argparse
import platform
from collections import defaultdict

# --- Configuration: Process Filtering ---

# Processes to always ignore. This is our primary filter.
PROCESS_BLACKLIST = {
    # macOS
    'kernel_task', 'launchd', 'cfprefsd', 'logd', 'UserEventAgent', 'runningboardd',
    'CommCenter', 'SpringBoard', 'backboardd', 'ReportCrash', 'spindump', 'WindowServer',
    'loginwindow', 'SystemUIServer', 'Dock', 'Finder', 'mds', 'mds_stores', 'mdworker',
    'mDNSResponder', 'coreaudiod', 'coreduetd', 'cloudd', 'bird', 'nsurlsessiond',
    'cfnetworkd', 'rapportd', 'sharingd', 'bluetoothd', 'timed', 'secd', 'trustd',
    'askpermissiond', 'dasd', 'AirPlayXPCHelper', 'universalaccessd', 'syspolicyd',
    'tccd', 'ScreenTime', 'distnoted', 'lsd',

    # Linux
    'systemd', 'kthreadd', 'kworker', 'ksoftirqd', 'dbus-daemon', 'udevd', 'rsyslogd',
    'cron', 'irqbalance', 'polkitd', 'udisksd', 'gdm', 'sddm', 'pipewire', 'wireplumber',
    'pulseaudio', 'Xorg', 'Xwayland', 'gnome-shell', 'kwin_x11',

    # Windows
    'system', 'registry', 'smss.exe', 'csrss.exe', 'wininit.exe', 'winlogon.exe',
    'services.exe', 'lsass.exe', 'svchost.exe', 'dwm.exe', 'explorer.exe',
    'sihost.exe', 'ctfmon.exe', 'fontdrvhost.exe', 'audiodg.exe', 'RuntimeBroker.exe',
}

def is_script_process(cmdline):
    """Check if a process is running this script"""
    if not cmdline:
        return False
    cmdline_str = ' '.join(cmdline)
    script_names = ['process_dj.py', 'top_process_dj.py', 'process_dj_refined.py']
    return any(script_name in cmdline_str for script_name in script_names)

def map_process_to_genre(process_name, cmdline_str=""):
    """Maps a process name to a music genre. Now includes cmdline for better context."""
    p_name = process_name.lower().replace('.exe', '')
    cmdline_lower = cmdline_str.lower()
    
    # Debug output to see what we're working with
    print(f"   DEBUG: Processing '{process_name}' -> '{p_name}'")

    # More reliable mapping for Mac apps running under generic names like 'Electron'
    if 'electron' in p_name:
        if 'visual studio code.app' in cmdline_lower: p_name = 'vscode'
        elif 'obsidian.app' in cmdline_lower: p_name = 'obsidian'
        elif 'slack.app' in cmdline_lower: p_name = 'slack'
        elif 'discord.app' in cmdline_lower: p_name = 'discord'
        elif 'whatsapp.app' in cmdline_lower: p_name = 'whatsapp'
        elif 'figma.app' in cmdline_lower: p_name = 'figma'
        elif 'notion.app' in cmdline_lower: p_name = 'notion'
        elif 'spotify.app' in cmdline_lower: p_name = 'spotify'

    # Gaming - check if any game keyword is in the process name
    gaming_keywords = [
        'steam', 'lutris', 'csgo', 'dota2', 'valorant', 'league of legends', 'fortnite',
        'minecraft', 'overwatch', 'apex legends', 'rocket league', 'cyberpunk2077',
        'elden ring', 'witcher3', 'gta', 'fifa', 'nba2k', 'call of duty', 'battlefield',
        'destiny2', 'warframe', 'world of warcraft', 'final fantasy', 'assassins creed',
        'far cry', 'tomb raider', 'skyrim', 'fallout', 'diablo', 'starcraft', 'hearthstone',
        'wow', 'lol', 'dota', 'pubg', 'among us', 'fall guys', 'rust', 'ark', 'terraria',
        'stardew valley', 'cities skylines', 'civilization', 'total war', 'age of empires',
        'counter-strike', 'rainbow six', 'sea of thieves', 'no mans sky', 'subnautica',
        'epic games', 'origin', 'uplay', 'battle.net', 'gog galaxy', 'gamepass'
    ]
    for keyword in gaming_keywords:
        if keyword in p_name:
            print(f"   DEBUG: Matched gaming keyword '{keyword}' -> epic orchestral")
            return "epic orchestral"
    
    # Development & Programming
    dev_keywords = [
        'code', 'vscode', 'cursor', 'pycharm', 'intellij', 'webstorm', 'phpstorm', 'clion', 'datagrip',
        'vim', 'nvim', 'neovim', 'emacs', 'sublime text', 'atom', 'brackets', 'notepad++',
        'xcode', 'android studio', 'unity', 'unreal engine', 'godot', 'blender',
        'docker', 'kubernetes', 'kubectl', 'helm', 'terraform', 'ansible', 'vagrant',
        'git', 'github desktop', 'sourcetree', 'gitkraken', 'fork', 'tower',
        'postman', 'insomnia', 'curl', 'wget', 'httpie', 'ngrok', 'localtunnel',
        'mysql workbench', 'pgadmin', 'dbeaver', 'tableplus', 'sequel pro', 'robo 3t',
        'redis-cli', 'mongodb compass', 'elasticsearch', 'kibana', 'grafana',
        'jupyter', 'anaconda', 'spyder', 'rstudio', 'matlab', 'octave',
        'node', 'npm', 'yarn', 'python', 'ruby', 'php', 'java', 'golang', 'rustc',
        'wireshark', 'burp suite', 'metasploit', 'nmap', 'sqlmap'
    ]
    for keyword in dev_keywords:
        if keyword in p_name:
            print(f"   DEBUG: Matched development keyword '{keyword}' -> lofi hip hop")
            return "lofi hip hop"
    
    # Web Browsing
    browser_keywords = [
        'chrome', 'firefox', 'safari', 'edge', 'brave', 'opera', 'vivaldi',
        'chromium', 'tor browser', 'librewolf', 'waterfox', 'seamonkey',
        'internet explorer', 'ie', 'msedge'
    ]
    for keyword in browser_keywords:
        if keyword in p_name:
            print(f"   DEBUG: Matched browser keyword '{keyword}' -> synthwave")
            return "synthwave"
    
    # Media & Entertainment
    media_keywords = [
        'spotify', 'apple music', 'youtube music', 'pandora', 'soundcloud',
        'vlc', 'mpv', 'quicktime', 'windows media player', 'media player classic',
        'kodi', 'plex', 'jellyfin', 'emby', 'netflix', 'hulu', 'disney+',
        'youtube', 'twitch', 'obs', 'streamlabs', 'xsplit', 'restream',
        'audacity', 'garage band', 'logic pro', 'ableton live', 'fl studio',
        'cubase', 'pro tools', 'reaper', 'reason', 'bitwig', 'studio one'
    ]
    if any(keyword in p_name for keyword in media_keywords):
        print(f"   DEBUG: Matched media -> chillwave")
        return "chillwave"
    
    # Communication & Social
    comm_keywords = [
        'discord', 'slack', 'teams', 'zoom', 'skype', 'webex', 'gotomeeting',
        'telegram', 'whatsapp', 'signal', 'messenger', 'imessage', 'facetime',
        'thunderbird', 'outlook', 'mail', 'gmail', 'yahoo mail', 'protonmail',
        'tweetdeck', 'twitter', 'facebook', 'instagram', 'linkedin', 'reddit',
        'mastodon', 'matrix', 'element', 'riot', 'irc', 'hexchat', 'weechat'
    ]
    if any(keyword in p_name for keyword in comm_keywords):
        print(f"   DEBUG: Matched communication -> upbeat pop")
        return "upbeat pop"
    
    # Terminals & Command Line
    terminal_keywords = [
        'terminal', 'iterm', 'alacritty', 'kitty', 'konsole', 'gnome-terminal',
        'xterm', 'urxvt', 'terminator', 'tilix', 'hyper', 'warp', 'tabby',
        'powershell', 'cmd', 'bash', 'zsh', 'fish', 'tmux', 'screen',
        'windows terminal', 'wt', 'pwsh'
    ]
    if any(keyword in p_name for keyword in terminal_keywords):
        print(f"   DEBUG: Matched terminal -> chiptune")
        return "chiptune"
    
    # Office & Productivity
    office_keywords = [
        'word', 'excel', 'powerpoint', 'outlook', 'onenote', 'access', 'publisher',
        'libreoffice', 'openoffice', 'writer', 'calc', 'impress', 'draw', 'base',
        'google docs', 'google sheets', 'google slides', 'google drive',
        'notion', 'obsidian', 'logseq', 'roam research', 'remnote', 'anki',
        'evernote', 'onenote', 'bear', 'drafts', 'ulysses', 'scrivener',
        'trello', 'asana', 'monday', 'clickup', 'todoist', 'things', 'omnifocus',
        'calendly', 'fantastical', 'calendar', 'reminders', 'notes'
    ]
    if any(keyword in p_name for keyword in office_keywords):
        print(f"   DEBUG: Matched office -> jazz")
        return "jazz"
    
    # Design & Creative
    design_keywords = [
        'photoshop', 'illustrator', 'indesign', 'after effects', 'premiere pro',
        'lightroom', 'bridge', 'acrobat', 'xd', 'dimension', 'animate',
        'figma', 'sketch', 'canva', 'affinity photo', 'affinity designer',
        'affinity publisher', 'pixelmator', 'gimp', 'inkscape', 'krita',
        'procreate', 'clip studio paint', 'paint tool sai', 'artrage',
        'zbrush', 'maya', '3ds max', 'cinema 4d', 'houdini', 'substance painter',
        'substance designer', 'marmoset toolbag', 'keyshot', 'vray', 'octane'
    ]
    if any(keyword in p_name for keyword in design_keywords):
        print(f"   DEBUG: Matched design -> ambient")
        return "ambient"
    
    # Video & Audio Editing
    video_keywords = [
        'final cut pro', 'davinci resolve', 'premiere pro', 'after effects',
        'avid media composer', 'filmora', 'camtasia', 'screenflow', 'handbrake',
        'ffmpeg', 'vlc', 'audacity', 'logic pro', 'pro tools', 'reaper',
        'hindenburg', 'izotope', 'waves', 'slate digital', 'universal audio'
    ]
    if any(keyword in p_name for keyword in video_keywords):
        print(f"   DEBUG: Matched video editing -> cinematic")
        return "cinematic"
    
    # File Management & System
    file_mgr_keywords = [
        'finder', 'explorer', 'nautilus', 'dolphin', 'thunar', 'pcmanfm',
        'ranger', 'nemo', 'caja', 'spacefm', 'double commander', 'total commander',
        'far manager', 'midnight commander', 'mc', 'ftp', 'sftp', 'rsync',
        'filezilla', 'cyberduck', 'transmit', 'winscp', 'putty', 'mobaxterm',
        'activity monitor', 'task manager', 'process explorer', 'htop', 'btop',
        'system monitor', 'resource monitor', 'performance monitor'
    ]
    if any(keyword in p_name for keyword in file_mgr_keywords):
        print(f"   DEBUG: Matched file management -> minimal techno")
        return "minimal techno"
    
    # Security & VPN
    security_keywords = [
        'nordvpn', 'expressvpn', 'surfshark', 'protonvpn', 'mullvad', 'windscribe',
        'tunnelbear', 'cyberghost', 'pia', 'hotspot shield', 'openvpn', 'wireguard',
        'lastpass', 'bitwarden', '1password', 'keeper', 'dashlane', 'keychain',
        'malwarebytes', 'norton', 'mcafee', 'kaspersky', 'bitdefender', 'avast',
        'avg', 'windows defender', 'clamav', 'sophos', 'eset'
    ]
    if any(keyword in p_name for keyword in security_keywords):
        print(f"   DEBUG: Matched security -> dark electronic")
        return "dark electronic"
    
    # Virtual Machines & Containers
    vm_keywords = [
        'vmware', 'virtualbox', 'parallels', 'qemu', 'kvm', 'hyperv',
        'docker', 'podman', 'containerd', 'kubernetes', 'k8s', 'minikube',
        'vagrant', 'lxc', 'lxd', 'wine', 'crossover', 'playonlinux'
    ]
    if any(keyword in p_name for keyword in vm_keywords):
        print(f"   DEBUG: Matched virtualization -> cyberpunk")
        return "cyberpunk"
    
    # Database & Data Tools
    db_keywords = [
        'mysql', 'postgresql', 'sqlite', 'mongodb', 'redis', 'elasticsearch',
        'cassandra', 'couchdb', 'influxdb', 'neo4j', 'dynamodb', 'firebase',
        'tableau', 'power bi', 'looker', 'qlik', 'superset', 'metabase',
        'jupyter', 'rstudio', 'spss', 'sas', 'stata', 'r-studio', 'r.exe',
        'spark', 'hadoop', 'kafka', 'airflow', 'prefect', 'dagster'
    ]
    if any(keyword in p_name for keyword in db_keywords):
        print(f"   DEBUG: Matched database -> progressive rock")
        return "progressive rock"
    
    # E-commerce & Business
    ecom_keywords = [
        'shopify', 'magento', 'woocommerce', 'prestashop', 'opencart',
        'salesforce', 'hubspot', 'pipedrive', 'zoho', 'freshworks',
        'quickbooks', 'xero', 'wave', 'sage', 'tally', 'peachtree',
        'stripe', 'paypal', 'square', 'adyen', 'klarna', 'razorpay'
    ]
    if any(keyword in p_name for keyword in ecom_keywords):
        print(f"   DEBUG: Matched ecommerce -> corporate smooth jazz")
        return "corporate smooth jazz"
    
    # Reading & Documentation
    reading_keywords = [
        'kindle', 'books', 'apple books', 'calibre', 'adobe reader', 'foxit',
        'sumatra pdf', 'evince', 'okular', 'preview', 'zathura', 'mupdf',
        'notion', 'obsidian', 'logseq', 'roam', 'dendron', 'foam',
        'gitbook', 'confluence', 'wiki', 'dokuwiki', 'mediawiki',
        'markdown', 'typora', 'mark text', 'ghostwriter', 'zettlr'
    ]
    if any(keyword in p_name for keyword in reading_keywords):
        print(f"   DEBUG: Matched reading -> acoustic folk")
        return "acoustic folk"

    print(f"   DEBUG: No match found, using default -> lofi hip hop")
    return "lofi hip hop"  # A good, neutral default

def get_process_name_map():
    """
    On some OSes (macOS), helpers have generic names. This function tries to map them
    to their parent application for more stable tracking.
    e.g., "Google Chrome Helper" -> "Google Chrome"
    """
    process_map = {}
    for p in psutil.process_iter(['pid', 'name', 'ppid']):
        try:
            # Simple heuristic: if a helper process is found, map its PID to its parent's name
            if 'Helper' in p.info['name'] or 'helper' in p.info['name']:
                parent = psutil.Process(p.info['ppid'])
                process_map[p.info['pid']] = parent.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return process_map

def get_top_apps(process_map, quiet=False):
    """
    Gets a dictionary of application CPU usage, coalescing helper processes.
    This is the key to stable CPU measurement.
    """
    app_cpu_usage = defaultdict(float)
    app_cmdlines = {} # Store a sample cmdline for each app for better mapping

    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'cmdline']):
        try:
            p_info = p.info
            p_name = p_info['name']

            # 1. Initial Filtering
            if not p_name or p_name in PROCESS_BLACKLIST:
                continue
            
            # Skip Python processes running this script
            if p_name.lower() in ['python', 'python3', 'python.exe', 'python3.exe']:
                if is_script_process(p_info['cmdline']):
                    continue

            # 2. Coalesce helper processes
            # If this PID is in our map (e.g., it's a helper), use the parent's name
            app_name = process_map.get(p_info['pid'], p_name)

            # 3. Aggregate CPU usage - handle None values
            cpu = p_info['cpu_percent']
            if cpu is not None and cpu > 0:
                app_cpu_usage[app_name] += cpu
                # Store the command line for context, prefer parent process's cmdline
                if app_name not in app_cmdlines:
                    app_cmdlines[app_name] = ' '.join(p_info['cmdline']) if p_info['cmdline'] else ''

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not app_cpu_usage:
        return None, None

    # Find the top application by summed CPU usage
    top_app_name = max(app_cpu_usage, key=app_cpu_usage.get)
    top_app_cmdline = app_cmdlines.get(top_app_name, "")
    
    if not quiet:
        # Debug print the top 5
        sorted_apps = sorted(app_cpu_usage.items(), key=lambda item: item[1], reverse=True)
        print("   --- Top 5 Active Applications ---")
        for name, cpu_total in sorted_apps[:5]:
            print(f"     - {name}: {cpu_total:.1f}%")
        print("   ---------------------------------")

    return top_app_name, top_app_cmdline

def change_server_genre(server_ip, server_port, genre):
    """Sends a POST request to the music server to change the genre."""
    url = f"http://{server_ip}:{server_port}/genre"
    payload = {"genre": genre}
    print(f"-> Attempting to change genre to '{genre}'...")
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        print(f"   SUCCESS: Genre changed to '{response.json().get('genre', genre)}'.")
    except requests.exceptions.RequestException as e:
        print(f"   ERROR: Could not connect to the music server at {url}. Details: {e}")

def main(args):
    """Main loop to monitor the top process and send genre changes."""
    print("--- Top Process DJ Starting ---")
    print(f"Checking for new top process every {args.interval} seconds.")
    print(f"Targeting server: http://{args.ip}:{args.port}/genre")
    print("Press Ctrl+C to stop.")

    last_top_app = None
    
    # Initialize psutil.cpu_percent. The first call is always 0.
    for p in psutil.process_iter(['cpu_percent']):
        pass

    try:
        while True:
            # Build a map of helper processes to their parents. This is lightweight.
            process_map = get_process_name_map()

            # This is where the magic happens. We get the top app after the sleep.
            # The cpu_percent values now reflect usage over the sleep interval.
            top_app, top_app_cmdline = get_top_apps(process_map, args.quiet)

            if top_app and top_app != last_top_app:
                print(f"\nNew top application: '{top_app}'")
                
                new_genre = map_process_to_genre(top_app, top_app_cmdline)
                change_server_genre(args.ip, args.port, new_genre)
                
                last_top_app = top_app
            elif not top_app and not args.quiet:
                print("...no significant user process activity detected.")

            # Sleep after checking, not before
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n--- Top Process DJ Stopping ---")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Monitors the system's top CPU process and changes music genre accordingly."
    )
    parser.add_argument("ip", help="The IP address of the music server.")
    parser.add_argument("port", type=int, help="The port of the music server.")
    parser.add_argument("--interval", type=int, default=10, help="Interval in seconds to check (default: 10).")
    parser.add_argument("--quiet", action="store_true", help="Reduce output noise.")

    parsed_args = parser.parse_args()
    main(parsed_args) 