import time
import threading
import queue
import numpy as np
import os
from magenta_rt import audio, system

# The frame size must match the Go server!
# 48000 Hz * 0.020 s = 960 samples per frame
# This is our target size for writing to the pipe.
PIPE_FRAME_SIZE = 960

class AudioFade:
    """Handles the cross fade between audio chunks.
    
    This is the same class used in the official magenta-realtime demo.
    """
    
    def __init__(self, chunk_size: int, num_chunks: int, stereo: bool):
        fade_size = chunk_size * num_chunks
        self.fade_size = fade_size
        self.num_chunks = num_chunks
        
        self.previous_chunk = np.zeros(fade_size)
        self.ramp = np.sin(np.linspace(0, np.pi / 2, fade_size)) ** 2
        
        if stereo:
            self.previous_chunk = self.previous_chunk[:, np.newaxis]
            self.ramp = self.ramp[:, np.newaxis]
    
    def reset(self):
        self.previous_chunk = np.zeros_like(self.previous_chunk)
    
    def __call__(self, chunk: np.ndarray) -> np.ndarray:
        chunk[: self.fade_size] *= self.ramp
        chunk[: self.fade_size] += self.previous_chunk
        self.previous_chunk = chunk[-self.fade_size :] * np.flip(self.ramp)
        return chunk[: -self.fade_size]

class ContinuousMusicPipeWriter:
    def __init__(self, style="synthwave", pipe_path="/tmp/audio_pipe"):
        self.style = style
        self.pipe_path = pipe_path
        self.genre_file_path = "/tmp/genre_request.txt"
        
        # Add a threading.Lock for safe buffer manipulation
        self.buffer_lock = threading.Lock()
        
        # Queue for generated audio chunks before they are split (reduced maxsize for lower latency)
        self.generation_queue = queue.Queue(maxsize=5)
        
        self.generator_thread = None
        self.pipe_writer_thread = None
        self.genre_monitor_thread = None
        self.stop_event = threading.Event()
        self.pipe_handle = None
        self.current_genre = style
        self.last_genre_check = 0

        # Make the writer's buffer an instance variable so the genre monitor can clear it
        self.buffered_audio = np.array([], dtype=np.int16)

        print("Magenta RT Continuous Music Pipe Writer")
        print("=" * 40)
        print("Initializing model...")
        
        start_time = time.time()
        self.mrt = system.MagentaRT(tag="base", device="gpu", skip_cache=False, lazy=False)
        init_time = time.time() - start_time
        print(f"Model loaded in {init_time:.1f} seconds")
        
        self.sample_rate = self.mrt.sample_rate
        self.channels = self.mrt.num_channels
        
        # Initialize buffered_audio with correct shape
        self.buffered_audio = self.buffered_audio.reshape(0, self.channels)
        
        print(f"Embedding style: '{self.style}'...")
        self.style_embedding = self.mrt.embed_style(self.style)
        
        # AudioFade setup
        chunk_size = int(self.mrt.config.crossfade_length * self.sample_rate)
        self.fade = AudioFade(chunk_size=chunk_size, num_chunks=1, stereo=(self.channels==2))
        self.generation_state = None
        
        print(f"Sample rate: {self.sample_rate} Hz")
        print(f"Channels: {self.channels}")
        print(f"Pipe frame size: {PIPE_FRAME_SIZE} samples")
        print(f"Genre file: {self.genre_file_path}")
        print("-" * 40)

    def _monitor_genre_changes(self):
        """Monitor the genre file for changes and update the style accordingly."""
        print("Starting genre monitor thread...")
        
        while not self.stop_event.is_set():
            try:
                # Check if genre file exists and has been modified
                if os.path.exists(self.genre_file_path):
                    file_mod_time = os.path.getmtime(self.genre_file_path)
                    
                    if file_mod_time > self.last_genre_check:
                        # File has been modified, read new genre
                        with open(self.genre_file_path, 'r') as f:
                            content = f.read().strip()
                        
                        # Parse the content (format: "SMOOTH:genre" or just "genre")
                        if content.startswith("SMOOTH:"):
                            new_genre = content[7:]  # Remove "SMOOTH:" prefix
                            smooth_transition = True
                        else:
                            new_genre = content
                            smooth_transition = False
                        
                        if new_genre and new_genre != self.current_genre:
                            print(f"Genre change detected: '{self.current_genre}' -> '{new_genre}'")
                            self.current_genre = new_genre
                            
                            # Re-embed the new style
                            print(f"   Embedding new style: '{new_genre}'...")
                            try:
                                self.style_embedding = self.mrt.embed_style(new_genre)
                                self.current_genre = new_genre
                                print(f"   Style embedded successfully!")
                                
                                # The core logic for fast transitions
                                print("   Clearing audio buffers for fast transition...")
                                with self.buffer_lock:
                                    # Empty the queue of pre-generated chunks
                                    while not self.generation_queue.empty():
                                        try:
                                            self.generation_queue.get_nowait()
                                        except queue.Empty:
                                            break
                                    
                                    # Clear the writer's internal buffer
                                    self.buffered_audio = np.array([], dtype=np.int16).reshape(0, self.channels)
                                    
                                    # Reset the fade processor to start the new genre cleanly
                                    self.fade.reset()
                                    # We keep the generation_state to ensure musical continuity
                                print("   Buffers cleared. New genre will start shortly.")
                                
                            except Exception as e:
                                print(f"   Error embedding style '{new_genre}': {e}")
                        
                        self.last_genre_check = file_mod_time
                
                # Check every 0.5 seconds
                time.sleep(0.5)
                
            except Exception as e:
                print(f"Error in genre monitor thread: {e}")
                time.sleep(1)
        
        print("Genre monitor thread stopped.")

    def _generation_loop(self):
        """Generates large audio chunks and puts them on a queue."""
        print("Starting audio generation thread...")
        chunk_count = 0
        while not self.stop_event.is_set():
            try:
                chunk_count += 1
                chunk, self.generation_state = self.mrt.generate_chunk(
                    state=self.generation_state,
                    style=self.style_embedding,
                    seed=chunk_count
                )
                faded_audio = self.fade(chunk.samples)
                
                # Check for hot signal (optional diagnostic)
                max_amp = np.abs(faded_audio).max()
                if max_amp > 1.0:
                    print(f"WARNING: Audio signal is hot! Max amplitude: {max_amp:.4f}")
                
                # Convert to 16-bit integers with proper clipping to prevent crackling
                audio_int16 = (np.clip(faded_audio, -1.0, 1.0) * 32767).astype(np.int16)
                
                # Put items onto the queue (queue is already thread-safe, no lock needed)
                self.generation_queue.put(audio_int16, timeout=5)
                
                if chunk_count % 10 == 0:
                    print(f"Generated chunk {chunk_count} (genre: {self.current_genre})")
            except queue.Full:
                print("WARNING: Generation queue is full. Generator is pausing.")
                time.sleep(0.5)  # Don't spin-lock
                continue
            except Exception as e:
                print(f"ERROR in generator thread: {e}")
                self.stop_event.set()
                break
        print("Audio generation thread stopped.")

    def _pipe_writer_loop(self):
        """Pulls from queue, splits into frames, and writes to pipe."""
        print("Starting pipe writer thread...")
        
        # Wait for the pipe to be opened by the Go server
        print(f"Opening pipe '{self.pipe_path}' for writing...")
        try:
            # This will block until the Go server opens it for reading
            self.pipe_handle = os.open(self.pipe_path, os.O_WRONLY)
            print("Pipe opened by a reader. Starting to write frames.")
        except Exception as e:
            print(f"FATAL: Could not open pipe: {e}")
            self.stop_event.set()
            return

        while not self.stop_event.is_set():
            try:
                # Check if we need more audio data
                with self.buffer_lock:
                    need_more_data = len(self.buffered_audio) < PIPE_FRAME_SIZE
                
                # Get new chunks if needed (outside the lock to avoid deadlock)
                if need_more_data:
                    new_chunk = self.generation_queue.get(timeout=1)
                    with self.buffer_lock:
                        self.buffered_audio = np.vstack([self.buffered_audio, new_chunk])
                
                # Get the next frame to send (with lock)
                with self.buffer_lock:
                    if len(self.buffered_audio) >= PIPE_FRAME_SIZE:
                        frame_to_send = self.buffered_audio[:PIPE_FRAME_SIZE]
                        self.buffered_audio = self.buffered_audio[PIPE_FRAME_SIZE:]
                    else:
                        continue  # Not enough data yet
                
                # Writing to the pipe can be done outside the lock
                os.write(self.pipe_handle, frame_to_send.tobytes())

            except queue.Empty:
                # This is normal during genre changes, so don't log a scary warning
                time.sleep(0.01)
                continue
            except Exception as e:
                print(f"ERROR in pipe writer thread (likely pipe closed): {e}")
                self.stop_event.set()
                break
                
        print("Pipe writer thread stopped.")
        if self.pipe_handle:
            os.close(self.pipe_handle)

    def start(self):
        self.stop_event.clear()
        
        self.generator_thread = threading.Thread(target=self._generation_loop)
        self.generator_thread.daemon = True
        
        self.pipe_writer_thread = threading.Thread(target=self._pipe_writer_loop)
        self.pipe_writer_thread.daemon = True
        
        self.genre_monitor_thread = threading.Thread(target=self._monitor_genre_changes)
        self.genre_monitor_thread.daemon = True

        self.generator_thread.start()
        self.pipe_writer_thread.start()
        self.genre_monitor_thread.start()

        print("\nMusic generator is running. Connect a client to start the stream.")
        print(f"Current genre: '{self.current_genre}'")
        print("Monitoring for genre changes...")
        print("Press Ctrl+C to stop")
        
        # Keep main thread alive to listen for Ctrl+C
        try:
            while not self.stop_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
        finally:
            self.stop()
            
    def stop(self):
        if self.stop_event.is_set():
            return
        
        print("\nStopping music writer...")
        self.stop_event.set()

        if self.pipe_writer_thread and self.pipe_writer_thread.is_alive():
            self.pipe_writer_thread.join(timeout=2)
        if self.generator_thread and self.generator_thread.is_alive():
            self.generator_thread.join(timeout=2)
        if self.genre_monitor_thread and self.genre_monitor_thread.is_alive():
            self.genre_monitor_thread.join(timeout=2)
        
        print("Music writer stopped.")

if __name__ == "__main__":
    writer = ContinuousMusicPipeWriter(style="synthwave")
    writer.start()