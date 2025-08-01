#!/usr/bin/env python3
"""
LLM DJ - Uses local LLM to determine music genre based on activity
"""

import time
import sys
import requests
import argparse
import json
import base64
import provider as pr
from io import BytesIO
from PIL import Image
from typing import Literal
import mss
from openai import OpenAI


def examine_activity(debug=False, monitor_index=0):
    """Take a screenshot of the current screen and return it as a base64 encoded string."""
    try:
        with mss.mss() as sct:
            # Take screenshot to share to the LLM
            # monitor_index 0 = all monitors combined, 1+ = specific monitor
            if monitor_index >= len(sct.monitors):
                print(f"   WARNING: Monitor {monitor_index} not found, using all monitors")
                monitor_index = 0
            
            monitor = sct.monitors[monitor_index]
            if monitor_index == 0:
                print(f"   Examining all monitors combined")
            else:
                print(f"   Examining monitor {monitor_index}")
            screenshot = sct.grab(monitor)
            
            # Convert to PIL Image
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            
            # Resize image to reduce file size (optional, but recommended for LLM processing)
            # Keep aspect ratio but limit max dimension to 1024px
            max_size = 1024
            if img.width > max_size or img.height > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            # Debug: Show the screenshot that will be sent
            if debug:
                print("   DEBUG: Opening screenshot preview...")
                img.show()
            
            # Convert to base64
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            img_str = base64.b64encode(buffer.getvalue()).decode()
            
            return img_str
    except Exception as e:
        print(f"ERROR: Failed to take screenshot: {e}")
        return None

SYSTEM_PROMPT = "### SYSTEM\nYou are given one image.\n\n### INSTRUCTION\n1. Silently infer what the user is doing in the screenshot.\n2. Pick one 1-2-word music genre that fits the activity.\n   *Think step-by-step internally only.*\n3. Return a JSON object that conforms to the provided schema.\n   **Do not output anything else.**\n\n### RESPONSE FORMAT\n{\"music_genre\": \"<genre>\"}"

def get_genre_from_llm_local(provider: pr.Provider, model_name, screenshot_b64):
    """Use local OpenAI-compatible server to get music genre from screenshot."""
    try:
        print(f"-> Analyzing activity with local model '{model_name}'...")
        
        # Request JSON output via optimized system prompt
        content = provider.query_genre(SYSTEM_PROMPT, screenshot_b64, model_name)
        
        try:
            # First, strip any markdown code blocks that might wrap the JSON
            import re
            # Remove ```json and ``` markers
            cleaned_content = re.sub(r'^```(?:json)?\s*\n?', '', content.strip(), flags=re.MULTILINE)
            cleaned_content = re.sub(r'\n?```\s*$', '', cleaned_content, flags=re.MULTILINE)
            
            genre_data = json.loads(cleaned_content.strip())
            if "music_genre" in genre_data and isinstance(genre_data["music_genre"], str):
                return genre_data["music_genre"]
            else:
                print(f"   WARNING: 'music_genre' key missing or invalid in LLM response: {content}")
                return None
        except json.JSONDecodeError:
            print(f"   WARNING: Could not parse JSON from LLM response: {content}")
            # Try to find JSON-like pattern in the text as fallback
            import re
            match = re.search(r'\{"music_genre":\s*"([^"]+)"\}', content)
            if match:
                return match.group(1)
            return None
        
    except Exception as e:
        print(f"   ERROR: Failed to get genre from local LM: {e}")
        return None


def change_server_genre(server_ip, server_port, genre):
    """Sends a POST request to the music server to change the genre."""
    url = f"http://{server_ip}:{server_port}/genre"
    payload = {"genre": genre}
    print(f"-> Attempting to change genre to '{genre}'...")
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        print(f"   SUCCESS: Genre changed to '{response.json().get('genre', genre)}'.")
        return True
    except requests.exceptions.RequestException as e:
        print(f"   ERROR: Could not connect to the music server at {url}. Details: {e}")
        return False

def model_provider_to_human(provider: Literal['lm-studio', 'ollama', 'vllm']) -> str:
    """Converts the provider name to human readable one"""
    if provider == 'lm-studio':
        return 'LM Studio'
    elif provider == 'ollama':
        return 'Ollama'
    elif provider == 'vllm':
        return 'vLLM'
    return 'Unkown Provider'

def get_provider(provider_name: Literal['lm-studio', 'ollama', 'vllm']) -> pr.Provider:
    """Returns the provider class based on a provider name"""
    if provider_name == 'lm-studio':
        return pr.OpenAiProvider
    elif provider_name == 'ollama':
        return pr.OllamaProvider
    elif provider_name == 'vllm':
        raise NotImplementedError('vLLM support is not implemented yet')
    
    print(f'The following provider {provider_name} may be supported! Defaulting to OpenAI provider!')
    return pr.OpenAiProvider

def main(args):
    """Main loop to take screenshots, get genre suggestions, and update music."""
    lm_studio_url = args.provider_url  # Only talk to local LM Studio

    provider_name = model_provider_to_human(args.model_provider)
    
    print("--- LLM DJ Starting ---")
    print(f"Screen Activity Analysis every {args.interval} seconds")
    print(f"{provider_name} URL: {lm_studio_url}")
    print(f"{provider_name} Model: {args.model}")
    print(f"Music Server: http://{args.music_ip}:{args.music_port}/genre")
    
    # Show monitor info
    try:
        with mss.mss() as sct:
            if args.monitor == 0:
                print(f"Monitor: All monitors combined")
            elif args.monitor < len(sct.monitors):
                monitor = sct.monitors[args.monitor]
                print(f"Monitor: Monitor {args.monitor} ({monitor['width']}x{monitor['height']})")
            else:
                print(f"Monitor: {args.monitor} (will fallback to all monitors)")
    except Exception as e:
        print(f"Monitor: Unable to detect monitor info - {e}")
    
    print("Press Ctrl+C to stop.")

    provider_class = get_provider(args.model_provider)

    provider = provider_class(url=lm_studio_url, api_key=args.api_key)
    
    last_genre = None
    
    try:
        while True:
            print(f"\n--- Screen Activity Analysis cycle at {time.strftime('%H:%M:%S')} ---")
            
            # Take screenshot
            screenshot_b64 = examine_activity(debug=args.debug, monitor_index=args.monitor)
            if not screenshot_b64:
                print("   Skipping this cycle due to screenshot failure.")
                time.sleep(args.interval)
                continue
            
            # Pass the client instance to the function
            suggested_genre = get_genre_from_llm_local(provider, args.model, screenshot_b64)
            if not suggested_genre:
                print("   No genre suggestion received from LLM.")
                time.sleep(args.interval)
                continue
            
            print(f"   LLM suggested genre: '{suggested_genre}'")
            
            # Only change if it's different from the last genre
            if suggested_genre.lower() != str(last_genre).lower():
                if change_server_genre(args.music_ip, args.music_port, suggested_genre):
                    last_genre = suggested_genre
                else:
                    print("   Failed to change genre on music server.")
            else:
                print("   Genre unchanged, skipping server update.")
            
            # Wait for next cycle
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\n--- LLM DJ Stopping ---")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Uses a localvision model via LM Studio (localhost:1234) to determine music genre."
    )
    parser.add_argument("music_ip", help="IP address of the music server")
    parser.add_argument("music_port", type=int, help="Port of the music server")
    parser.add_argument("--model", default="local-model", help="Model identifier to use (default: 'local-model', which LM Studio often uses)")
    parser.add_argument("--interval", type=int, default=10, help="Interval in seconds between screen analysis (default: 10)")
    parser.add_argument("--monitor", type=int, default=1, help="Monitor to capture (0=all monitors, 1=first monitor, 2=second monitor, etc.)")
    parser.add_argument("--list-monitors", action="store_true", help="List available monitors and exit")
    parser.add_argument("--debug", action="store_true", help="Show screenshot preview before sending to LLM to determine monitor")
    parser.add_argument("--provider-url", default="http://localhost:1234/v1", help="The url for a model provider. (default: 'http://localhost:1234/v1')")
    parser.add_argument("--model-provider", '-p', default='lm-studio', choices=['lm-studio', 'ollama', 'vllm'], help="The model provider to use. (default: 'lm-studio')")
    parser.add_argument("--api-key", default='lm-studio', help="The api-key for the model provider. Not always a requirement depending on the provider. (default: 'lm-studio')")
    
    parsed_args = parser.parse_args()
    
    # Handle monitor listing
    if parsed_args.list_monitors:
        print("Available monitors:")
        try:
            with mss.mss() as sct:
                for i, monitor in enumerate(sct.monitors):
                    if i == 0:
                        print(f"  {i}: All monitors combined ({monitor['width']}x{monitor['height']})")
                    else:
                        print(f"  {i}: Monitor {i} ({monitor['width']}x{monitor['height']} at {monitor['left']},{monitor['top']})")
        except Exception as e:
            print(f"Error listing monitors: {e}")
        sys.exit(0)
    
    main(parsed_args)
