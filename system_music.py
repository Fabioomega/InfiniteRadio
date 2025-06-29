#!/usr/bin/env python3
"""
System Music Genre Predictor

This script monitors system processes and suggests music genres based on 
what applications are currently using the most system resources.

Usage:
python system_music.py
"""

import subprocess
import re
import time
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

@dataclass
class ProcessInfo:
    """Information about a running process"""
    name: str
    cpu_percent: float
    memory_percent: float
    pid: int
    command: str

class ProcessGenreMapper:
    """Maps process names to music genres using rules and patterns"""
    
    def __init__(self):
        # Define mappings from process patterns to music genres
        self.genre_rules = {
            # Development & Programming
            'code|vscode|vim|emacs|atom|sublime|intellij|pycharm|webstorm': 
                ['lo-fi hip hop', 'ambient', 'electronic', 'jazz'],
            
            'python|node|java|gcc|make|cmake|git': 
                ['coding beats', 'lo-fi', 'ambient electronic'],
            
            'docker|kubernetes|kubectl': 
                ['techno', 'electronic', 'cyberpunk'],
            
            # Games
            'steam|game|unity|unreal|minecraft|wow|cs2|dota': 
                ['epic orchestral', 'video game music', 'electronic rock'],
            
            # Browsers & Web
            'firefox|chrome|chromium|brave|safari|edge': 
                ['pop', 'indie', 'acoustic', 'chill'],
            
            # Media & Creative
            'vlc|mpv|spotify|youtube|netflix|obs|kdenlive|gimp|blender|photoshop': 
                ['cinematic', 'soundtrack', 'ambient', 'creative'],
            
            'audacity|reaper|fl.*studio|ableton|cubase': 
                ['experimental', 'electronic', 'ambient'],
            
            # System & Terminal
            'bash|zsh|fish|terminal|gnome-terminal|konsole|htop|top': 
                ['cyberpunk', 'synthwave', 'dark ambient'],
            
            # Communication
            'discord|slack|teams|zoom|skype|telegram|whatsapp': 
                ['upbeat', 'pop', 'indie pop', 'cheerful'],
            
            # Scientific & Analysis
            'jupyter|matlab|r|rstudio|mathematica|sage': 
                ['classical', 'minimalist', 'focus music'],
            
            # AI/ML
            'python.*tensorflow|pytorch|cuda|nvidia': 
                ['futuristic', 'synthwave', 'electronic', 'ambient techno'],
            
            # Database
            'mysql|postgres|mongodb|redis|elasticsearch': 
                ['minimal techno', 'ambient', 'downtempo'],
            
            # Virtualization
            'virtualbox|vmware|qemu': 
                ['trance', 'electronic', 'synthwave'],
            
            # Default categories
            'apache|nginx|httpd': ['elevator music', 'background'],
            'systemd|init|kernel': ['dark ambient', 'drone'],
        }
        
        # Fallback genres for unknown processes
        self.fallback_genres = ['ambient', 'lo-fi', 'chill', 'background music']
        
    def get_genre_for_process(self, process_info: ProcessInfo) -> List[str]:
        """Get suggested music genres for a given process"""
        process_name = process_info.name.lower()
        command = process_info.command.lower()
        
        # Check each rule pattern
        for pattern, genres in self.genre_rules.items():
            if re.search(pattern, process_name) or re.search(pattern, command):
                return genres
        
        # If no specific rule matches, return fallback genres
        return self.fallback_genres
        
    def get_weighted_genre_suggestion(self, processes: List[ProcessInfo]) -> Dict[str, float]:
        """Get weighted genre suggestions based on multiple processes"""
        genre_weights = {}
        total_cpu = sum(p.cpu_percent for p in processes)
        
        if total_cpu == 0:
            return {'ambient': 1.0}
        
        for process in processes:
            if process.cpu_percent < 1.0:  # Skip low-CPU processes
                continue
                
            genres = self.get_genre_for_process(process)
            weight = process.cpu_percent / total_cpu
            
            for genre in genres:
                if genre not in genre_weights:
                    genre_weights[genre] = 0
                genre_weights[genre] += weight
        
        # Normalize weights
        if genre_weights:
            total_weight = sum(genre_weights.values())
            genre_weights = {k: v/total_weight for k, v in genre_weights.items()}
        else:
            genre_weights = {'ambient': 1.0}
        
        return genre_weights

class SystemMonitor:
    """Monitor system processes and resource usage"""
    
    def get_top_processes(self, limit: int = 10) -> List[ProcessInfo]:
        """Get top processes by CPU usage"""
        try:
            # Use ps command to get process information
            cmd = ['ps', 'aux', '--sort=-pcpu']
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            processes = []
            lines = result.stdout.strip().split('\n')[1:]  # Skip header
            
            for line in lines[:limit]:
                parts = line.split(None, 10)  # Split on whitespace, max 11 parts
                if len(parts) >= 11:
                    try:
                        cpu_percent = float(parts[2])
                        memory_percent = float(parts[3])
                        pid = int(parts[1])
                        command = parts[10]
                        
                        # Extract process name from command
                        process_name = command.split()[0].split('/')[-1]
                        
                        processes.append(ProcessInfo(
                            name=process_name,
                            cpu_percent=cpu_percent,
                            memory_percent=memory_percent,
                            pid=pid,
                            command=command
                        ))
                    except (ValueError, IndexError):
                        continue
            
            return processes
            
        except subprocess.CalledProcessError as e:
            print(f"Error getting process info: {e}")
            return []
    
    def get_system_load(self) -> Dict[str, float]:
        """Get system load averages"""
        try:
            with open('/proc/loadavg', 'r') as f:
                load_data = f.read().strip().split()
                return {
                    'load_1min': float(load_data[0]),
                    'load_5min': float(load_data[1]),
                    'load_15min': float(load_data[2])
                }
        except Exception:
            return {'load_1min': 0, 'load_5min': 0, 'load_15min': 0}

class MusicGenreSuggester:
    """Main class that combines system monitoring with genre prediction"""
    
    def __init__(self):
        self.monitor = SystemMonitor()
        self.mapper = ProcessGenreMapper()
        
    def get_current_music_suggestion(self) -> Dict:
        """Get current music genre suggestion based on system state"""
        # Get top processes
        processes = self.monitor.get_top_processes(limit=5)
        system_load = self.monitor.get_system_load()
        
        if not processes:
            return {
                'primary_genre': 'ambient',
                'genres': {'ambient': 1.0},
                'reasoning': 'No active processes detected',
                'top_process': None,
                'system_load': system_load
            }
        
        # Get genre suggestions
        genre_weights = self.mapper.get_weighted_genre_suggestion(processes)
        primary_genre = max(genre_weights.items(), key=lambda x: x[1])[0]
        
        # Create reasoning
        top_process = processes[0]
        reasoning = f"Based on '{top_process.name}' using {top_process.cpu_percent:.1f}% CPU"
        
        return {
            'primary_genre': primary_genre,
            'genres': genre_weights,
            'reasoning': reasoning,
            'top_process': {
                'name': top_process.name,
                'cpu_percent': top_process.cpu_percent,
                'command': top_process.command[:50] + '...' if len(top_process.command) > 50 else top_process.command
            },
            'system_load': system_load,
            'all_processes': [
                {
                    'name': p.name,
                    'cpu_percent': p.cpu_percent,
                    'suggested_genres': self.mapper.get_genre_for_process(p)
                }
                for p in processes[:3]
            ]
        }

def main():
    """Main function to demonstrate the system music genre suggester"""
    print("System Music Genre Suggester")
    print("=" * 50)
    print("Monitoring system processes and suggesting music genres...")
    print("Press Ctrl+C to stop\n")
    
    suggester = MusicGenreSuggester()
    
    try:
        while True:
            suggestion = suggester.get_current_music_suggestion()
            
            # Clear screen and move cursor to top
            print('\033[2J\033[H', end='')
            
            print("System Music Genre Suggester")
            print("=" * 50)
            print(f"Primary Genre: {suggestion['primary_genre'].upper()}")
            print(f"Reasoning: {suggestion['reasoning']}")
            
            if suggestion['top_process']:
                top = suggestion['top_process']
                print(f"Top Process: {top['name']} ({top['cpu_percent']:.1f}% CPU)")
                print(f"Command: {top['command']}")
            
            print(f"System Load: {suggestion['system_load']['load_1min']:.2f}")
            
            print("\nGenre Breakdown:")
            for genre, weight in sorted(suggestion['genres'].items(), key=lambda x: x[1], reverse=True):
                bar_length = int(weight * 20)
                bar = '█' * bar_length + '░' * (20 - bar_length)
                print(f"   {genre:20} {bar} {weight:.1%}")
            
            print("\nProcess Analysis:")
            for proc in suggestion['all_processes']:
                genres_str = ', '.join(proc['suggested_genres'][:2])
                print(f"   {proc['name']:15} ({proc['cpu_percent']:4.1f}%) -> {genres_str}")
            
            print("\n" + "="*50)
            print("Press Ctrl+C to stop")
            time.sleep(10)  # Wait a little before updating or it'll get crazy
            # TODO: maybe make the wait a little longer when not testing
            
    except KeyboardInterrupt:
        print("\nFinished playing music.")

if __name__ == "__main__":
    main()
