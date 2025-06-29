import time
import threading
import queue
import numpy as np
import sounddevice as sd
from magenta_rt import audio, system

# Use a standard, reliable buffer size for audio streaming
STREAM_BLOCK_SIZE = 1024

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

class ContinuousMusicPlayer:
    def __init__(self, style="synthwave", buffer_size=8):
        self.style = style
        # Queue for processed audio buffers ready for playback
        self.playback_queue = queue.Queue(maxsize=200)
        
        self.generator_thread = None
        self.stream = None
        self.stop_event = threading.Event()

        print("Magenta RT Continuous Music Player")
        print("=" * 40)
        print(f"Initializing model...")
        
        start_time = time.time()
        self.mrt = system.MagentaRT(
            tag="base",
            device="gpu",
            skip_cache=False,
            lazy=False
        )
        init_time = time.time() - start_time
        print(f"Model loaded in {init_time:.1f} seconds")
        
        self.sample_rate = self.mrt.sample_rate
        print(f"Embedding style: '{self.style}'...")
        self.style_embedding = self.mrt.embed_style(self.style)
        
        # Initialize AudioFade for seamless crossfading
        # chunk_size=1920 corresponds to 40ms at 48kHz (the crossfade length)
        chunk_size = int(self.mrt.config.crossfade_length * self.sample_rate)
        self.fade = AudioFade(chunk_size=chunk_size, num_chunks=1, stereo=True)
        self.generation_state = None
        
        print(f"Sample rate: {self.sample_rate} Hz")
        print(f"Channels: {self.mrt.num_channels}")
        print(f"Crossfade: {self.mrt.config.crossfade_length * 1000:.1f} ms")
        print(f"Fade size: {chunk_size} samples")
        print(f"Stream block size: {STREAM_BLOCK_SIZE} frames")
        print("-" * 40)

    def _generate_and_process_chunks(self):
        """Single thread that generates chunks and processes them with AudioFade."""
        print("Starting chunk generation and processing thread...")
        chunk_count = 0
        
        while not self.stop_event.is_set():
            try:
                chunk_count += 1
                
                # Generate chunk
                chunk, self.generation_state = self.mrt.generate_chunk(
                    state=self.generation_state,
                    style=self.style_embedding,
                    seed=chunk_count
                )
                
                print(f"Generated chunk {chunk_count}, shape: {chunk.samples.shape}")
                
                # Apply AudioFade for seamless crossfading
                # chunk.samples is in (samples, channels) format
                faded_audio = self.fade(chunk.samples)
                
                print(f"Faded audio shape: {faded_audio.shape}, max amplitude: {np.abs(faded_audio).max():.3f}")
                
                # Split into small buffers for streaming
                self._split_into_buffers(faded_audio)
                
            except Exception as e:
                print(f"   ERROR in generator/processor thread: {e}")
                import traceback
                traceback.print_exc()
                self.stop_event.set()
                break
                
        print("Chunk generation and processing thread stopped.")

    def _split_into_buffers(self, audio_data):
        """Split large audio chunk into small fixed-size buffers."""
        num_samples = audio_data.shape[0]
        
        for i in range(0, num_samples, STREAM_BLOCK_SIZE):
            if self.stop_event.is_set():
                break
                
            end_idx = min(i + STREAM_BLOCK_SIZE, num_samples)
            buffer = audio_data[i:end_idx]
            
            # Pad the last buffer if necessary
            if buffer.shape[0] < STREAM_BLOCK_SIZE:
                padding_needed = STREAM_BLOCK_SIZE - buffer.shape[0]
                padding = np.zeros((padding_needed, buffer.shape[1]), dtype=np.float32)
                buffer = np.vstack([buffer, padding])
            
            try:
                self.playback_queue.put(buffer, timeout=1)
            except queue.Full:
                # This should be rare with proper buffering
                print("   WARNING: Playback buffer full")
                break

    def _audio_callback(self, outdata, frames, time, status):
        """Sounddevice callback: Plays the processed audio buffers."""
        if status:
            print(f"Audio callback status: {status}", flush=True)

        assert frames == STREAM_BLOCK_SIZE, f"Expected {STREAM_BLOCK_SIZE} frames, got {frames}"

        try:
            buffer = self.playback_queue.get_nowait()
            outdata[:] = buffer
        except queue.Empty:
            print("   WARNING: Playback buffer underrun! Playing silence.", flush=True)
            outdata.fill(0)

    def start(self):
        """Starts the generator thread and audio stream."""
        self.stop_event.clear()
        
        # Start single background thread for generation and processing
        self.generator_thread = threading.Thread(target=self._generate_and_process_chunks)
        self.generator_thread.daemon = True
        self.generator_thread.start()
        
        # Pre-fill the playback buffer
        print("Pre-filling playback buffer...")
        target_buffer_size = 30
        
        timeout_counter = 0
        max_timeout = 300  # 30 seconds max wait
        
        while self.playback_queue.qsize() < target_buffer_size and timeout_counter < max_timeout:
            if self.stop_event.is_set():
                print("Thread died during pre-fill. Exiting.")
                return
            if not self.generator_thread.is_alive():
                print("Generator thread died during pre-fill. Exiting.")
                return
            time.sleep(0.1)
            timeout_counter += 1
            
            # Print progress every 5 seconds
            if timeout_counter % 50 == 0:
                print(f"Buffer status: {self.playback_queue.qsize()}/{target_buffer_size} buffers ready...")
            
        current_buffer_size = self.playback_queue.qsize()
        if current_buffer_size < target_buffer_size:
            print(f"WARNING: Only {current_buffer_size} buffers ready, but proceeding anyway...")
        else:
            print(f"Buffer ready with {current_buffer_size} buffers. Starting playback.")
        
        # Start audio stream
        try:
            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                blocksize=STREAM_BLOCK_SIZE,
                channels=self.mrt.num_channels,
                callback=self._audio_callback,
                dtype='float32'
            )
            self.stream.start()
            
            print(f"\n🎵 Music is playing seamlessly! 🎵")
            print(f"Press Ctrl+C to stop")
            print("-" * 40)
            
            # Keep main thread alive
            while not self.stop_event.is_set():
                time.sleep(2)
                # Optional: print buffer status if low
                buffer_count = self.playback_queue.qsize()
                if buffer_count < 5:
                    print(f"   Buffer low: {buffer_count} buffers remaining")

        except Exception as e:
            print(f"Error during stream setup: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.stop()

    def stop(self):
        """Stops the stream and all threads gracefully."""
        if self.stop_event.is_set():
            return
            
        print("\nStopping music player...")
        self.stop_event.set()

        # Stop audio stream first
        if self.stream:
            self.stream.stop()
            self.stream.close()
            print("Audio stream stopped.")

        # Clear queue to unblock thread
        try:
            while not self.playback_queue.empty():
                self.playback_queue.get_nowait()
        except:
            pass

        # Wait for thread to finish
        if self.generator_thread and self.generator_thread.is_alive():
            self.generator_thread.join(timeout=3)
            print("Generator thread stopped.")
        
        print("Music player stopped.")


def main():
    player = None
    try:
        player = ContinuousMusicPlayer(
            style="cello"
        )
        player.start()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if player:
            player.stop()

if __name__ == "__main__":
    main()
