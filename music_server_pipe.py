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
        # Queue for generated audio chunks before they are split
        self.generation_queue = queue.Queue(maxsize=10)
        
        self.generator_thread = None
        self.pipe_writer_thread = None
        self.stop_event = threading.Event()
        self.pipe_handle = None

        print("Magenta RT Continuous Music Pipe Writer")
        print("=" * 40)
        print("Initializing model...")
        
        start_time = time.time()
        self.mrt = system.MagentaRT(tag="base", device="gpu", skip_cache=False, lazy=False)
        init_time = time.time() - start_time
        print(f"Model loaded in {init_time:.1f} seconds")
        
        self.sample_rate = self.mrt.sample_rate
        self.channels = self.mrt.num_channels
        print(f"Embedding style: '{self.style}'...")
        self.style_embedding = self.mrt.embed_style(self.style)
        
        # AudioFade setup
        chunk_size = int(self.mrt.config.crossfade_length * self.sample_rate)
        self.fade = AudioFade(chunk_size=chunk_size, num_chunks=1, stereo=(self.channels==2))
        self.generation_state = None
        
        print(f"Sample rate: {self.sample_rate} Hz")
        print(f"Channels: {self.channels}")
        print(f"Pipe frame size: {PIPE_FRAME_SIZE} samples")
        print("-" * 40)

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
                # Convert to 16-bit integers, which is what the Go server expects
                audio_int16 = (faded_audio * 32767).astype(np.int16)
                self.generation_queue.put(audio_int16, timeout=5)
                
                if chunk_count % 10 == 0:
                    print(f"Generated chunk {chunk_count}")
            except queue.Full:
                print("WARNING: Generation queue is full. Generator is pausing.")
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

        buffered_audio = np.array([], dtype=np.int16).reshape(0, self.channels)

        while not self.stop_event.is_set():
            try:
                # Keep a buffer of at least one frame
                while len(buffered_audio) < PIPE_FRAME_SIZE:
                    # Get a new large chunk if our buffer is low
                    new_chunk = self.generation_queue.get(timeout=1)
                    buffered_audio = np.vstack([buffered_audio, new_chunk])

                # Get the next frame to send
                frame_to_send = buffered_audio[:PIPE_FRAME_SIZE]
                buffered_audio = buffered_audio[PIPE_FRAME_SIZE:]

                # Write the raw bytes to the pipe
                os.write(self.pipe_handle, frame_to_send.tobytes())

            except queue.Empty:
                print("WARNING: Generation queue is empty. Writer is waiting.")
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

        self.generator_thread.start()
        self.pipe_writer_thread.start()

        print("\n🎵 Music generator is running. Connect a client to start the stream. 🎵")
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
        
        print("Music writer stopped.")

if __name__ == "__main__":
    writer = ContinuousMusicPipeWriter(style="synthwave")
    writer.start()