import time
import threading
import queue
import numpy as np
import os
from magenta_rt import system

# The frame size must match the Go server!
# 48000 Hz * 0.020 s = 960 samples per frame
PIPE_FRAME_SIZE = 960

class AudioFade:
    """Handles the short, intra-chunk crossfade from Magenta's model."""
    def __init__(self, chunk_size: int, num_chunks: int, stereo: bool):
        fade_size = chunk_size * num_chunks
        self.fade_size = fade_size
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
    def __init__(self, style="lofi hip hop", pipe_path="/tmp/audio_pipe"):
        self.style = style
        self.pipe_path = pipe_path
        self.genre_file_path = "/tmp/genre_request.txt"
        
        # --- State Machine and Buffers ---
        self.buffer_lock = threading.Lock()
        self.transition_state = 'NORMAL'  # Can be 'NORMAL' or 'TRANSITIONING'
        self.transition_duration = 8.0  # seconds
        self.transition_start_time = 0
        self.fade_out_buffer = np.array([], dtype=np.int16) # Holds old genre for fading
        
        # --- Queues and Threads ---
        self.generation_queue = queue.Queue(maxsize=5)
        self.generator_thread = None
        self.pipe_writer_thread = None
        self.genre_monitor_thread = None
        self.stop_event = threading.Event()
        self.pipe_handle = None
        self.current_genre = style
        self.last_genre_check = 0

        # --- Internal Buffers and Model ---
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
        self.buffered_audio = self.buffered_audio.reshape(0, self.channels)
        self.fade_out_buffer = self.fade_out_buffer.reshape(0, self.channels)
        
        print(f"Embedding style: '{self.style}'...")
        self.style_embedding = self.mrt.embed_style(self.style)
        
        chunk_size = int(self.mrt.config.crossfade_length * self.sample_rate)
        self.fade = AudioFade(chunk_size=chunk_size, num_chunks=1, stereo=(self.channels==2))
        self.generation_state = None
        
        print("-" * 40)

    def _monitor_genre_changes(self):
        """Monitors for genre changes and triggers the transition state."""
        print("Starting genre monitor thread...")
        while not self.stop_event.is_set():
            try:
                if os.path.exists(self.genre_file_path):
                    file_mod_time = os.path.getmtime(self.genre_file_path)
                    if file_mod_time > self.last_genre_check:
                        with open(self.genre_file_path, 'r') as f:
                            content = f.read().strip()
                        
                        new_genre = content.split(":")[-1] # Gets genre from "SMOOTH:genre" or "genre"
                        
                        if new_genre and new_genre != self.current_genre:
                            print(f"Genre change detected: '{self.current_genre}' -> '{new_genre}'")
                            
                            try:
                                new_embedding = self.mrt.embed_style(new_genre)
                                print("   New style embedded. Triggering crossfade transition.")
                                
                                # --- THIS IS THE CRITICAL TRANSITION TRIGGER ---
                                with self.buffer_lock:
                                    # 1. Update generator to produce the new genre immediately
                                    self.style_embedding = new_embedding
                                    self.current_genre = new_genre
                                    self.fade.reset() # Reset intra-chunk fade for the new genre

                                    # 2. Collect all buffered audio from the OLD genre
                                    # Start with the partially-used chunk in the main buffer
                                    old_audio_chunks = [self.buffered_audio]
                                    # Then, drain the queue and APPEND each chunk to our list
                                    while not self.generation_queue.empty():
                                        try:
                                            old_audio_chunks.append(self.generation_queue.get_nowait())
                                        except queue.Empty:
                                            break
                                    
                                    # 3. Store the combined audio in the dedicated fade_out_buffer
                                    # np.vstack correctly stacks the arrays of shape (n_samples, channels)
                                    self.fade_out_buffer = np.vstack(old_audio_chunks)
                                    # Clear the main buffer so it can start filling with the NEW genre's audio
                                    self.buffered_audio = np.array([], dtype=np.int16).reshape(0, self.channels)
                                    
                                    # 4. Set the state machine to begin the crossfade
                                    self.transition_state = 'TRANSITIONING'
                                    self.transition_start_time = time.time()
                                    # --- END OF CORRECTED LOGIC ---
                                
                            except Exception as e:
                                print(f"   Error embedding style '{new_genre}': {e}")
                        
                        self.last_genre_check = file_mod_time
                time.sleep(0.5)
            except Exception as e:
                print(f"Error in genre monitor thread: {e}")
                time.sleep(1)
        print("Genre monitor thread stopped.")

    def _generation_loop(self):
        """Generates audio based on the current self.style_embedding. Blissfully unaware of transitions."""
        print("Starting audio generation thread...")
        chunk_count = 0
        while not self.stop_event.is_set():
            try:
                chunk_count += 1
                
                # The monitor thread changes self.style_embedding, the generator just uses it
                chunk, self.generation_state = self.mrt.generate_chunk(
                    state=self.generation_state,
                    style=self.style_embedding,
                    seed=chunk_count
                )
                faded_audio = self.fade(chunk.samples)
                audio_int16 = (np.clip(faded_audio, -1.0, 1.0) * 32767).astype(np.int16)
                
                self.generation_queue.put(audio_int16, timeout=5)
            except queue.Full:
                time.sleep(0.5)
                continue
            except Exception as e:
                print(f"ERROR in generator thread: {e}")
                self.stop_event.set()
                break
        print("Audio generation thread stopped.")

    def _pipe_writer_loop(self):
        """Writes to the pipe, handling 'NORMAL' and 'TRANSITIONING' states."""
        print("Starting pipe writer thread...")
        try:
            self.pipe_handle = os.open(self.pipe_path, os.O_WRONLY)
            print("Pipe opened by a reader. Starting to write frames.")
        except Exception as e:
            print(f"FATAL: Could not open pipe: {e}")
            self.stop_event.set()
            return

        while not self.stop_event.is_set():
            frame_to_send = None
            if self.transition_state == 'TRANSITIONING':
                frame_to_send = self._get_transitioning_frame()
            else: # NORMAL state
                frame_to_send = self._get_normal_frame()

            if frame_to_send is not None:
                try:
                    os.write(self.pipe_handle, frame_to_send.tobytes())
                except Exception as e:
                    print(f"ERROR writing to pipe (likely closed): {e}")
                    self.stop_event.set()
                    break
            else:
                # Not enough data to form a frame, wait briefly
                time.sleep(0.01)

        print("Pipe writer thread stopped.")
        if self.pipe_handle:
            os.close(self.pipe_handle)

    def _get_normal_frame(self):
        """Gets one frame of audio in the NORMAL state."""
        with self.buffer_lock:
            # Buffer more audio if we don't have enough for a full frame
            while len(self.buffered_audio) < PIPE_FRAME_SIZE:
                try:
                    new_chunk = self.generation_queue.get_nowait()
                    self.buffered_audio = np.vstack([self.buffered_audio, new_chunk])
                except queue.Empty:
                    return None # Not enough data available right now

            # Extract one frame
            frame = self.buffered_audio[:PIPE_FRAME_SIZE]
            self.buffered_audio = self.buffered_audio[PIPE_FRAME_SIZE:]
            return frame

    def _get_transitioning_frame(self):
        """Gets one frame of audio by mixing old and new genres."""
        with self.buffer_lock:
            # --- Check if transition is finished ---
            elapsed = time.time() - self.transition_start_time
            if elapsed >= self.transition_duration:
                print("   Crossfade transition complete. Switching to NORMAL state.")
                self.transition_state = 'NORMAL'
                self.fade_out_buffer = np.array([], dtype=np.int16).reshape(0, self.channels)
                # Any remaining old audio is discarded, which is fine.
                return None # Let the normal loop take over

            # --- Get audio from OLD genre buffer ---
            if len(self.fade_out_buffer) >= PIPE_FRAME_SIZE:
                old_frame = self.fade_out_buffer[:PIPE_FRAME_SIZE].astype(np.float32) / 32767.0
                self.fade_out_buffer = self.fade_out_buffer[PIPE_FRAME_SIZE:]
            else:
                # Pad with silence if old genre buffer is exhausted before transition ends
                old_frame = np.zeros((PIPE_FRAME_SIZE, self.channels), dtype=np.float32)

            # --- Get audio from NEW genre buffer ---
            # This logic is identical to _get_normal_frame, ensuring we have new audio
            while len(self.buffered_audio) < PIPE_FRAME_SIZE:
                try:
                    new_chunk = self.generation_queue.get_nowait()
                    self.buffered_audio = np.vstack([self.buffered_audio, new_chunk])
                except queue.Empty:
                    return None # Not enough new genre data yet, wait.
            
            new_frame = self.buffered_audio[:PIPE_FRAME_SIZE].astype(np.float32) / 32767.0
            self.buffered_audio = self.buffered_audio[PIPE_FRAME_SIZE:]

            # --- Mix the frames ---
            progress = min(elapsed / self.transition_duration, 1.0) # Clamp progress to 1.0
            
            # Smoother, more gradual crossfade curve
            # Use a smoothstep function for more gradual transitions
            smooth_progress = progress * progress * (3.0 - 2.0 * progress)  # smoothstep
            fade_out_volume = 1.0 - smooth_progress  # Fades 1 to 0
            fade_in_volume = smooth_progress  # Fades 0 to 1
            
            mixed_frame_float = (old_frame * fade_out_volume) + (new_frame * fade_in_volume)
            
            # Clip and convert back to int16
            return (np.clip(mixed_frame_float, -1.0, 1.0) * 32767).astype(np.int16)

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
        try:
            while not self.stop_event.is_set(): time.sleep(1)
        except KeyboardInterrupt: print("\nInterrupted by user.")
        finally: self.stop()
            
    def stop(self):
        if self.stop_event.is_set(): return
        print("\nStopping music writer...")
        self.stop_event.set()
        if self.pipe_writer_thread and self.pipe_writer_thread.is_alive(): self.pipe_writer_thread.join(timeout=2)
        if self.generator_thread and self.generator_thread.is_alive(): self.generator_thread.join(timeout=2)
        if self.genre_monitor_thread and self.genre_monitor_thread.is_alive(): self.genre_monitor_thread.join(timeout=2)
        print("Music writer stopped.")

if __name__ == "__main__":
    writer = ContinuousMusicPipeWriter(style="lofi hip hop")
    writer.start()