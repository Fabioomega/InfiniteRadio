import rumps
import subprocess
import os
import webbrowser
import sys
import signal
from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID
from Cocoa import (NSApplication, NSWindow, NSTextView, NSScrollView, NSMakeRect, 
                   NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskResizable, 
                   NSBackingStoreBuffered, NSFont, NSViewWidthSizable, NSViewHeightSizable)
from Foundation import NSObject, NSTimer
import objc

APP_ICON = "icon.png"

class ConsoleWindow(NSObject):
    """A proper console window with scrollable text, auto-refresh, and delegate handling."""
    
    # Let's remove the typedSelector decorators, they can be brittle.
    # The default dynamic dispatch is often sufficient.
    def initWithProcessRunner_andTitle_(self, process_runner, title):
        self = objc.super(ConsoleWindow, self).init()
        if self:
            self.process_runner = process_runner
            self.title = title
            self.console_window = None
            self.text_view = None
            self.timer = None
        return self
    
    def show(self):
        """Creates the window if it doesn't exist, or brings it to the front if it does."""
        if not self.console_window:
            self._create_window()
        
        self.console_window.makeKeyAndOrderFront_(None)
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
    
    def _create_window(self):
        """Handles the one-time creation of the window and its views."""
        rect = NSMakeRect(100, 100, 700, 450) # A bit wider for logs
        self.console_window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskResizable,
            NSBackingStoreBuffered,
            False
        )
        self.console_window.setTitle_(self.title)
        self.console_window.setReleasedWhenClosed_(False) # IMPORTANT: Don't destroy the window object on close
        self.console_window.setDelegate_(self) # KEY FIX #1: Set self as the delegate
        
        scroll_view = NSScrollView.alloc().initWithFrame_(self.console_window.contentView().bounds())
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        
        self.text_view = NSTextView.alloc().initWithFrame_(scroll_view.bounds())
        self.text_view.setEditable_(False)
        self.text_view.setFont_(NSFont.fontWithName_size_("Menlo", 11.0) or NSFont.userFixedPitchFontOfSize_(11.0))
        
        scroll_view.setDocumentView_(self.text_view)
        self.console_window.contentView().addSubview_(scroll_view)
        
        # Start the timer when the window is created
        self._start_timer()
        self.update_content() # Call the Python method directly for the initial update
    
    def _start_timer(self):
        """Starts a Cocoa NSTimer that is managed by the main run loop."""
        if self.timer:
            self.timer.invalidate()
        
        # <<< THE KEY FIX IS HERE >>>
        # We tell the timer to call a simple method name.
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0,
            self,
            'timerFired:', # Use a standard Objective-C method name
            None,
            True
        )

    # --- This is our timer callback method ---
    def timerFired_(self, timer):
        """This Objective-C compatible stub is called by NSTimer."""
        # It immediately calls our pure Python method.
        self.update_content()
        
    def update_content(self): # This is now a pure Python method
        """Updates the text view with the latest output from the process."""
        if not self.text_view or not self.process_runner:
            return
            
        current_text = self.text_view.string()
        new_output = self.process_runner.get_output()
        
        if current_text != new_output:
            print(f"Updating console with {len(new_output)} characters")
            self.text_view.setString_(new_output)
            self.text_view.scrollToEndOfDocument_(None) # Use None for the sender

    # --- Delegate Methods (No changes here, but remove decorator) ---
    def windowShouldClose_(self, sender):
        """
        Delegate method called when the user clicks the close button.
        We hide the window instead of closing it.
        """
        self.console_window.orderOut_(None)
        return False

    def force_close(self):
        """A method to permanently close the window and stop its timer."""
        if self.timer:
            self.timer.invalidate()
            self.timer = None
        
        if self.console_window:
            self.console_window.setDelegate_(None) # Unset delegate before closing
            self.console_window.close()
            self.console_window = None

def check_screen_recording_permission():
    """
    Checks for screen recording permission on macOS.
    This function attempts a harmless CoreGraphics call that requires the permission.
    If permission is not granted, macOS will show the system prompt.
    Returns True if permission is likely granted, False otherwise.
    """
    try:
        # This is a bit of a hack, but it's the most common way to trigger the prompt.
        # We list windows, which requires screen recording permission.
        # An empty list is returned if permission is not granted.
        window_list = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
        
        # On first run, window_list will be None and the system prompt will appear.
        # On subsequent runs without permission, it's an empty list.
        # If permission is granted, it will have items.
        # We check if the list is not None and has more than 0 items as a proxy.
        # A more robust check might look for a specific window like Finder.
        if window_list is not None and len(window_list) > 0:
            print("Screen recording permission appears to be granted.")
            return True
        else:
            print("Screen recording permission not granted. System prompt should appear.")
            # The prompt is handled by the OS. We just need to inform the user.
            return False
    except Exception as e:
        print(f"Error checking screen recording permission: {e}")
        return False

class ProcessRunner:
    """A helper class to manage a single background subprocess."""
    def __init__(self, script_name, args):
        self.script_name = script_name
        self.args = args
        self.process = None
        self.output_buffer = []
        self.max_buffer_lines = 1000  # Keep last 1000 lines

    def start(self):
        if not self.is_running():
            script_path = os.path.join(os.path.dirname(__file__), self.script_name)
            if not os.path.exists(script_path):
                rumps.alert(f"Error: Script not found!", f"The script '{self.script_name}' was not found.")
                return False
            
            # Use sys.executable to get the bundled Python executable
            command = [sys.executable, script_path] + self.args
            print(f"Starting process: {' '.join(command)}")
            
            # Clear output buffer
            self.output_buffer = []
            
            # Start the process in a new process group and capture output
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                universal_newlines=True,
                bufsize=1,  # Line buffered
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None
            )
            
            # Start a thread to read output continuously
            import threading
            self.output_thread = threading.Thread(target=self._read_output, daemon=True)
            self.output_thread.start()
            
            return True
        return False

    def stop(self):
        if self.is_running():
            print("Stopping process...")
            try:
                # Try to terminate the entire process group
                if hasattr(os, 'killpg'):
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                else:
                    self.process.terminate()
                    
                # Wait for the process to finish
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                # Force kill if it doesn't terminate gracefully
                try:
                    if hasattr(os, 'killpg'):
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    else:
                        self.process.kill()
                except OSError:
                    pass
                    
            self.process = None
            return True
        return False

    def is_running(self):
        return self.process is not None and self.process.poll() is None
    
    def _read_output(self):
        """Read output from the subprocess in a separate thread."""
        if not self.process or not self.process.stdout:
            return
            
        try:
            while self.process and self.process.poll() is None:
                line = self.process.stdout.readline()
                if line:
                    # Add timestamp and store in buffer
                    import time
                    timestamp = time.strftime('%H:%M:%S')
                    formatted_line = f"[{timestamp}] {line.rstrip()}"
                    self.output_buffer.append(formatted_line)
                    
                    # Keep buffer size manageable
                    if len(self.output_buffer) > self.max_buffer_lines:
                        self.output_buffer.pop(0)
                        
        except Exception as e:
            print(f"Error reading output: {e}")
            
    def get_output(self):
        """Get the current output buffer as a string."""
        return '\n'.join(self.output_buffer)

class InfiniteRadioApp(rumps.App):
    def __init__(self):
        super(InfiniteRadioApp, self).__init__("Infinite Radio", icon=APP_ICON, template=True, quit_button=None)
        
        self.ip = None
        self.port = None
        self.dj_type = "process"  # "process" or "llm"
        self.model_name = "internvl3-2b-instruct"  # Default model name for LLM DJ
        self.monitor_index = 1  # Default to first monitor
        self.interval = 10  # Default interval in seconds
        self.console_window_controller = None  # Renamed for clarity
        
        # Clean up any orphaned DJ processes from previous runs
        self.cleanup_orphaned_processes()
        
        self.dj_runner = ProcessRunner(
            script_name='process_dj.py',
            args=[] # Arguments will be set after configuration
        )
        
        self.rebuild_menu()
        
        self.status_updater = rumps.Timer(self.update_status, 1)
        self.status_updater.start()

    def cleanup_orphaned_processes(self):
        """
        Clean up any orphaned DJ processes from previous app runs.
        This is especially important after macOS permission prompts that kill and restart the app.
        """
        try:
            import psutil
            
            killed_processes = []
            
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    cmdline = proc.info['cmdline']
                    if not cmdline:
                        continue
                        
                    cmdline_str = ' '.join(cmdline)
                    
                    # Look for our DJ scripts
                    if ('llm_dj.py' in cmdline_str or 'process_dj.py' in cmdline_str):
                        # Make sure it's not the current process
                        if proc.pid != os.getpid():
                            print(f"Found orphaned DJ process: PID {proc.pid} - {cmdline_str}")
                            proc.terminate()
                            killed_processes.append(f"PID {proc.pid}")
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                    
            if killed_processes:
                print(f"Cleaned up orphaned processes: {', '.join(killed_processes)}")
            else:
                print("No orphaned DJ processes found")
                
        except Exception as e:
            print(f"Error during cleanup: {e}")

    def rebuild_menu(self):
        """Clears and rebuilds the menu to reflect the current state."""
        self.menu.clear()
        
        # Display current settings or "Not Set"
        display_ip = self.ip or "Not Set"
        display_port = self.port or "Not Set"
        display_dj_type = "Process DJ" if self.dj_type == "process" else "LLM DJ"
        display_model = self.model_name or "Not Set"
        display_monitor = self._get_monitor_description()
        display_interval = f"{self.interval}s"
        
        is_configured = self.ip is not None and self.port is not None

        # Create menu items
        dj_title = f"Start {display_dj_type}"
        start_dj_item = rumps.MenuItem(dj_title, callback=self.toggle_dj_process if is_configured else None)
        open_ui_item = rumps.MenuItem("Open Infinite Radio UI", callback=self.open_ui if is_configured else None)
        
        # Console output menu item
        console_output_item = rumps.MenuItem("Show Console Output", callback=self.show_console_output)
        
        # Build menu
        self.menu = [
            start_dj_item,
            open_ui_item,
            console_output_item,
            rumps.separator,
            {
                "DJ Type": [
                    rumps.MenuItem("Process DJ", callback=self.set_process_dj),
                    rumps.MenuItem("LLM DJ", callback=self.set_llm_dj),
                    rumps.separator,
                    rumps.MenuItem(f"Current: {display_dj_type}", callback=None),
                ]
            },
            {
                "Settings": [
                    rumps.MenuItem("Configure Server", callback=self.configure_server),
                    rumps.MenuItem("Configure Model", callback=self.configure_model),
                    rumps.MenuItem("Configure Monitor", callback=self.configure_monitor) if self.dj_type == "llm" else None,
                    rumps.MenuItem("Configure Interval", callback=self.configure_interval),
                    rumps.separator,
                    rumps.MenuItem(f"IP: {display_ip}", callback=None),
                    rumps.MenuItem(f"Port: {display_port}", callback=None),
                    rumps.MenuItem(f"Model: {display_model}", callback=None),
                    rumps.MenuItem(f"Monitor: {display_monitor}", callback=None) if self.dj_type == "llm" else None,
                    rumps.MenuItem(f"Interval: {display_interval}", callback=None),
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
            dj_type_name = "Process DJ" if self.dj_type == "process" else "LLM DJ"
            if self.dj_runner.is_running():
                self.start_dj_item.title = f"Stop {dj_type_name}"
            else:
                self.start_dj_item.title = f"Start {dj_type_name}"

    def toggle_dj_process(self, sender):
        """Starts or stops the DJ process. Will only be callable if configured."""
        if self.dj_runner.is_running():
            self.dj_runner.stop()
            # We don't need to close the console window anymore, just let it be.
            # It will show "process stopped" message.
            self.update_status(None)
            return

        if self.dj_type == "llm":
            if not check_screen_recording_permission():
                rumps.alert(
                    title="Permission Required",
                    message="Infinite Radio needs Screen Recording permission to work in LLM mode.\n\nPlease go to System Settings > Privacy & Security > Screen Recording, and enable it for this app.\n\nThe system prompt should have appeared. If not, please add the app manually."
                )
                return # Stop the function here

        # If permission is granted (or not needed for process_dj), proceed.
        self._update_runner_config()
        self.dj_runner.start()
        self.update_status(None)
    
    def _update_runner_config(self):
        """Updates the process runner configuration based on current settings."""
        if self.dj_type == "process":
            self.dj_runner.script_name = 'process_dj.py'
            self.dj_runner.args = [self.ip, str(self.port), '--interval', str(self.interval)]
        elif self.dj_type == "llm":
            self.dj_runner.script_name = 'llm_dj.py'
            self.dj_runner.args = [self.ip, str(self.port), '--model', self.model_name, '--monitor', str(self.monitor_index), '--interval', str(self.interval)]

    def open_ui(self, _):
        """Opens the web UI. Will only be callable if configured."""
        url = f"http://{self.ip}:{self.port}"
        print(f"Opening URL: {url}")
        webbrowser.open(url)
    
    def show_console_output(self, _):
        """Shows the console output of the running DJ process in a scrollable window with auto-refresh."""
        if not self.dj_runner.is_running():
            rumps.alert("No Process Running", "The DJ process is not currently running.")
            return
            
        # Create or show the console window
        dj_type_name = "Process DJ" if self.dj_type == "process" else "LLM DJ"
        window_title = f"{dj_type_name} Console Output"
        
        # KEY FIX #3: Re-instantiate the controller only if it's gone
        if not self.console_window_controller:
            self.console_window_controller = ConsoleWindow.alloc().initWithProcessRunner_andTitle_(
                self.dj_runner, window_title
            )
        
        self.console_window_controller.show()

    def _cleanup_console(self):
        """Helper to properly close the console window and release resources."""
        if self.console_window_controller:
            self.console_window_controller.force_close()
            self.console_window_controller = None
            
    def set_process_dj(self, _):
        """Switch to Process DJ mode."""
        was_running = self.dj_runner.is_running()
        if was_running:
            self.dj_runner.stop()
        
        self._cleanup_console() # Clean up console on type switch
        
        # Set appropriate default interval for Process DJ if it's currently set to LLM DJ default
        if self.dj_type == "llm" and self.interval == 10:
            self.interval = 5  # Process DJ default
        
        self.dj_type = "process"
        self.rebuild_menu()
        
        rumps.notification("DJ Type Changed", "Switched to Process DJ", "Monitors CPU usage to determine music genre.")
        
        if was_running:
            self.toggle_dj_process(None)
    
    def set_llm_dj(self, _):
        """Switch to LLM DJ mode."""
        was_running = self.dj_runner.is_running()
        if was_running:
            self.dj_runner.stop()
        
        self._cleanup_console() # Clean up console on type switch
        
        # Set appropriate default interval for LLM DJ if it's currently set to Process DJ default
        if self.dj_type == "process" and self.interval == 5:
            self.interval = 10  # LLM DJ default
        
        self.dj_type = "llm"
        self.rebuild_menu()
        
        rumps.notification("DJ Type Changed", "Switched to LLM DJ", "Uses LLM to analyze activity for music genre.")
        
        if was_running:
            self.toggle_dj_process(None)
    
    def _get_monitor_description(self):
        """Get a human-readable description of the current monitor selection."""
        try:
            import mss
            with mss.mss() as sct:
                if self.monitor_index == 0:
                    return "All monitors"
                elif self.monitor_index < len(sct.monitors):
                    monitor = sct.monitors[self.monitor_index]
                    return f"Monitor {self.monitor_index} ({monitor['width']}x{monitor['height']})"
                else:
                    return f"Monitor {self.monitor_index} (invalid)"
        except Exception:
            return f"Monitor {self.monitor_index}"
    
    def _get_available_monitors(self):
        """Get a list of available monitors."""
        try:
            import mss
            with mss.mss() as sct:
                monitors = []
                for i, monitor in enumerate(sct.monitors):
                    if i == 0:
                        monitors.append(f"{i}: All monitors ({monitor['width']}x{monitor['height']})")
                    else:
                        monitors.append(f"{i}: Monitor {i} ({monitor['width']}x{monitor['height']})")
                return monitors
        except Exception as e:
            return [f"Error: {e}"]
    
    def configure_monitor(self, _):
        """Opens a dialog to let the user select which monitor to use."""
        # Get available monitors
        monitor_options = self._get_available_monitors()
        
        # Create description text for the window
        description = "Available monitors:\n" + "\n".join(monitor_options)
        description += f"\n\nCurrent: {self.monitor_index}\nEnter monitor number:"
        
        monitor_window = rumps.Window(
            title="Select Monitor",
            message=description,
            default_text=str(self.monitor_index),
            ok="Save", cancel="Cancel", dimensions=(80, 20)  # Smaller text box
        )
        
        response = monitor_window.run()
        
        if not response.clicked:
            return
        
        try:
            new_monitor = int(response.text.strip())
            if new_monitor < 0:
                raise ValueError("Monitor index must be 0 or greater")
        except ValueError:
            rumps.alert("Invalid Input", "Please enter a valid monitor number (0 for all monitors, 1+ for specific monitor).")
            return
        
        was_running = self.dj_runner.is_running()
        if was_running:
            self.dj_runner.stop()
        
        self.monitor_index = new_monitor
        self.rebuild_menu()
        
        monitor_desc = self._get_monitor_description()
        rumps.notification("Monitor Updated", f"Monitor set to {monitor_desc}", "LLM DJ will capture this monitor.")
        
        if was_running:
            self.toggle_dj_process(None)
    
    def configure_interval(self, _):
        """Opens a dialog to let the user set the update interval."""
        dj_type_name = "Process DJ" if self.dj_type == "process" else "LLM DJ"
        
        # Create description text for the window
        description = f"Set how often {dj_type_name} checks for changes.\n\n"
        description += f"\nCurrent: {self.interval} seconds\nEnter new interval:"
        
        interval_window = rumps.Window(
            title="Update Interval",
            message=description,
            default_text=str(self.interval),
            ok="Save", cancel="Cancel", dimensions=(80, 20)
        )
        
        response = interval_window.run()
        
        if not response.clicked:
            return
        
        try:
            new_interval = int(response.text.strip())
            if new_interval < 1:
                raise ValueError("Interval must be at least 1 second")
            if new_interval > 300:  # 5 minutes max
                raise ValueError("Interval must be 300 seconds or less")
        except ValueError as e:
            rumps.alert("Invalid Input", f"Please enter a valid interval (1-300 seconds). {e}")
            return
        
        was_running = self.dj_runner.is_running()
        if was_running:
            self.dj_runner.stop()
        
        self.interval = new_interval
        self.rebuild_menu()
        
        rumps.notification("Interval Updated", f"Update interval set to {self.interval} seconds", f"{dj_type_name} will check for changes every {self.interval} seconds.")
        
        if was_running:
            self.toggle_dj_process(None)
    
    def configure_model(self, _):
        """Opens a window to let the user set the model name for LLM DJ."""
        model_window = rumps.Window(
            title="LLM Model Name",
            default_text=self.model_name,
            ok="Save", cancel="Cancel", dimensions=(200, 20)
        )
        response = model_window.run()
        
        if not response.clicked:
            return
        
        new_model = response.text.strip()
        if not new_model:
            rumps.alert("Invalid Input", "Model name cannot be empty.")
            return
        
        was_running = self.dj_runner.is_running()
        if was_running:
            self.dj_runner.stop()
        
        self.model_name = new_model
        self.rebuild_menu()
        
        rumps.notification("Model Updated", f"Model set to {self.model_name}", "LLM DJ will use this model.")
        
        if was_running:
            self.toggle_dj_process(None)
    
    def configure_server(self, _):
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
        
        # Rebuild the menu to enable buttons and show new settings
        self.rebuild_menu()
        
        rumps.notification("Settings Applied", f"Server set to {self.ip}:{self.port}", "You can now start the DJ script.")

        if was_running:
            self.toggle_dj_process(None)
            
    def quit_app(self, _):
        """Custom quit method that stops the DJ process before quitting."""
        print("Quit requested. Stopping background process...")
        self.dj_runner.stop()
        self._cleanup_console() # Use the helper to close console on quit
        print("Process stopped. Exiting.")
        rumps.quit_application()
    
    def before_quit(self):
        """Ensure the background process is stopped before the app quits."""
        self.quit_app(None)


if __name__ == "__main__":
    app = InfiniteRadioApp()
    app.run()