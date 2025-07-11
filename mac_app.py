import rumps
import subprocess
import os
import webbrowser
import sys

APP_ICON = "icon.png"

class ProcessRunner:
    """A helper class to manage a single background subprocess."""
    def __init__(self, script_name, args):
        self.script_name = script_name
        self.args = args
        self.process = None

    def start(self):
        if not self.is_running():
            script_path = os.path.join(os.path.dirname(__file__), self.script_name)
            if not os.path.exists(script_path):
                rumps.alert(f"Error: Script not found!", f"The script '{self.script_name}' was not found.")
                return False
            
            # Use sys.executable to get the bundled Python executable
            command = [sys.executable, script_path] + self.args
            print(f"Starting process: {' '.join(command)}")
            self.process = subprocess.Popen(command)
            return True
        return False

    def stop(self):
        if self.is_running():
            print("Stopping process...")
            self.process.terminate()
            self.process.wait()
            self.process = None
            return True
        return False

    def is_running(self):
        return self.process is not None and self.process.poll() is None

class InfiniteRadioApp(rumps.App):
    def __init__(self):
        super(InfiniteRadioApp, self).__init__("Infinite Radio", icon=APP_ICON, template=True, quit_button=None)
        
        self.ip = None
        self.port = None
        
        self.dj_runner = ProcessRunner(
            script_name='process_dj.py',
            args=[] # Arguments will be set after configuration
        )
        
        self.rebuild_menu()
        
        self.status_updater = rumps.Timer(self.update_status, 1)
        self.status_updater.start()

    def rebuild_menu(self):
        """Clears and rebuilds the menu to reflect the current state."""
        self.menu.clear()
        
        # Display current settings or "Not Set"
        display_ip = self.ip or "Not Set"
        display_port = self.port or "Not Set"
        
        is_configured = self.ip is not None and self.port is not None

        # Create menu items
        start_dj_item = rumps.MenuItem("Start Process DJ", callback=self.toggle_dj_process if is_configured else None)
        open_ui_item = rumps.MenuItem("Open Infinite Radio UI", callback=self.open_ui if is_configured else None)
        
        # Set titles based on configuration
        if not is_configured:
            start_dj_item.title = "Start Process DJ"
            open_ui_item.title = "Open UI"
        
        # Build menu
        self.menu = [
            start_dj_item,
            open_ui_item,
            rumps.separator,
            {
                "Settings": [
                    rumps.MenuItem("Configure", callback=self.configure_settings),
                    rumps.separator,
                    rumps.MenuItem(f"IP: {display_ip}", callback=None),
                    rumps.MenuItem(f"Port: {display_port}", callback=None),
                ]
            },
            rumps.separator,
            rumps.MenuItem("Quit", callback=self.quit_app)
        ]
        
        # Store references for later updates
        self.start_dj_item = start_dj_item
        self.open_ui_item = open_ui_item
        
        self.update_status(None)

    def update_status(self, _):
        """Timer callback to update the 'Start/Stop' button title."""
        is_configured = self.ip is not None and self.port is not None
        if not is_configured:
            return # Don't update if not configured

        if hasattr(self, 'start_dj_item'):
            if self.dj_runner.is_running():
                self.start_dj_item.title = "Stop Process DJ"
            else:
                self.start_dj_item.title = "Start Process DJ"

    def toggle_dj_process(self, sender):
        """Starts or stops the DJ process. Will only be callable if configured."""
        if self.dj_runner.is_running():
            self.dj_runner.stop()
        else:
            self.dj_runner.start()
        self.update_status(None)

    def open_ui(self, _):
        """Opens the web UI. Will only be callable if configured."""
        url = f"http://{self.ip}:{self.port}"
        print(f"Opening URL: {url}")
        webbrowser.open(url)
            
    def configure_settings(self, _):
        """Opens a window to let the user set the IP and Port."""
        was_running = self.dj_runner.is_running()
        
        # Prepare default text showing current settings
        if self.ip or self.port:
            current_setting = f"{self.ip or ''}:{self.port or ''}"
            if current_setting.endswith(":"):
                current_setting = current_setting[:-1]
        else:
            current_setting = "192.168.1.100:8080"
        
        # Single dialog for both IP and port
        config_window = rumps.Window(
            title="Music Server",
            default_text=current_setting,
            ok="Save", cancel="Cancel", dimensions=(150, 20)
        )
        response = config_window.run()
        
        if not response.clicked:
            return
        
        # Parse the input
        input_text = response.text.strip()
        if not input_text:
            rumps.alert("Invalid Input", "Please enter IP and port in the format IP:PORT")
            return
        
        # Split by colon
        if ':' not in input_text:
            rumps.alert("Invalid Input", "Please use the format IP:PORT (e.g., 192.168.1.100:8080)")
            return
        
        try:
            ip_part, port_part = input_text.rsplit(':', 1)  # Split from the right to handle IPv6
            new_ip = ip_part.strip()
            new_port_str = port_part.strip()
            
            if not new_ip:
                rumps.alert("Invalid Input", "IP Address cannot be empty.")
                return
            
            new_port = int(new_port_str)
            if not (0 < new_port < 65536): 
                raise ValueError("Port out of range")
                
        except ValueError:
            rumps.alert("Invalid Input", "Port must be a number between 1 and 65535.")
            return
        except Exception:
            rumps.alert("Invalid Input", "Please use the format IP:PORT (e.g., 192.168.1.100:8080)")
            return

        if was_running:
            self.dj_runner.stop()
        
        # Update the in-memory state
        self.ip = new_ip
        self.port = new_port
        
        # Update the process runner with the new arguments
        self.dj_runner.args = [self.ip, str(self.port)]
        
        # Rebuild the menu to enable buttons and show new settings
        self.rebuild_menu()
        
        rumps.notification("Settings Applied", f"Server set to {self.ip}:{self.port}", "You can now start the DJ script.")

        if was_running:
            self.dj_runner.start()
            
    def quit_app(self, _):
        """Custom quit method that stops the DJ process before quitting."""
        print("Quit requested. Stopping background process...")
        self.dj_runner.stop()
        print("Process stopped. Exiting.")
        rumps.quit_application()
    
    def before_quit(self):
        """Ensure the background process is stopped before the app quits."""
        print("Quit requested. Stopping background process...")
        self.dj_runner.stop()
        print("Process stopped. Exiting.")


if __name__ == "__main__":
    app = InfiniteRadioApp()
    app.run()