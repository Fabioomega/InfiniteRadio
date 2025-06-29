import time
import numpy as np
import sounddevice as sd
from magenta_rt import audio, system

def main():
    print("Magenta RT Demo with Working Audio")
    print("=" * 40)
    
    # Configuration
    style = "synthwave"  # You can change this
    num_chunks = 5       # About 10 seconds of music
    
    print(f"Initializing Magenta RT (GPU) from cache...")
    print(f"   - Style: '{style}'")
    print(f"   - Chunks: {num_chunks}")
    print("   - Using pre-cached model (should be fast!)")
    
    # Initialize the model with GPU support
    # Model files are pre-downloaded during Docker build
    start_time = time.time()
    mrt = system.MagentaRT(
        tag="base",           # Use base model (pre-cached)
        device="gpu",         # Use GPU instead of TPU
        skip_cache=False,     # Use cache (already downloaded)
        lazy=False           # Load model immediately
    )
    
    init_time = time.time() - start_time
    print(f"Model loaded in {init_time:.1f} seconds")
    
    # Embed the style prompt
    print(f"Embedding style: '{style}'...")
    style_embedding = mrt.embed_style(style)
    
    # Generate and play chunks sequentially
    print(f"Generating and playing {num_chunks} chunks...")
    state = None
    
    for i in range(num_chunks):
        print(f"   Generating chunk {i+1}/{num_chunks}...", end=" ", flush=True)
        chunk_start = time.time()
        
        # Generate chunk
        chunk, state = mrt.generate_chunk(state=state, style=style_embedding)
        
        chunk_time = time.time() - chunk_start
        max_amp = np.max(np.abs(chunk.samples)) if hasattr(chunk, 'samples') else 0.0
        print(f"({chunk_time:.2f}s, max_amp: {max_amp:.3f})")
        
        # Play chunk immediately using the working method
        if hasattr(chunk, 'samples') and len(chunk.samples) > 0:
            print(f"   Playing chunk {i+1}...")
            
            # Ensure audio is float32 format (like working test.py)
            audio_data = chunk.samples.astype(np.float32)
            
            # Play using the simple method that works
            sd.play(audio_data, samplerate=mrt.sample_rate)
            sd.wait()  # Wait for chunk to finish playing
            
            print(f"   Chunk {i+1} playback complete")
        else:
            print(f"   ERROR: Chunk {i+1} has no audio data")
    
    print("=" * 40)
    print("Demo Complete!")
    print(f"Total time: {time.time() - start_time:.1f}s")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
