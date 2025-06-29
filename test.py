#!/usr/bin/env python3
"""
Basic Magenta RT Demo for Local GPU Usage

This script demonstrates how to use the Magenta RT model locally on GPU
to generate music. It creates a simple demo that generates a few chunks
of music and saves them to a WAV file.

Make sure you have installed magenta_rt with GPU support:
pip install 'git+https://github.com/magenta/magenta-realtime#egg=magenta_rt[gpu]'
"""

import time
import numpy as np
from magenta_rt import audio, system

def main():
    print("Magenta RT Basic Demo")
    print("=" * 40)
    
    # Configuration
    num_seconds = 10  # Total duration of music to generate
    style_prompt = "synthwave"  # Style for the music
    output_file = "generated_music.wav"
    
    print(f"Initializing Magenta RT (GPU) from cache...")
    print(f"   - Duration: {num_seconds} seconds")
    print(f"   - Style: '{style_prompt}'")
    print(f"   - Output: {output_file}")
    print(f"   - Using pre-cached model (should be fast!)")
    
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
    print(f"Model initialized in {init_time:.1f} seconds")
    
    # Embed the style prompt
    print(f"Embedding style prompt: '{style_prompt}'...")
    style = mrt.embed_style(style_prompt)
    
    # Generate music in chunks
    print(f"Generating {num_seconds} seconds of music...")
    chunks = []
    state = None
    
    num_chunks = round(num_seconds / mrt.config.chunk_length)
    print(f"   - Generating {num_chunks} chunks of {mrt.config.chunk_length}s each")
    
    generation_start = time.time()
    for i in range(num_chunks):
        print(f"   - Chunk {i+1}/{num_chunks}...", end=" ", flush=True)
        
        chunk_start = time.time()
        chunk, state = mrt.generate_chunk(state=state, style=style)
        chunk_time = time.time() - chunk_start
        
        chunks.append(chunk)
        print(f"({chunk_time:.2f}s)")
    
    generation_time = time.time() - generation_start
    print(f"Generation complete in {generation_time:.1f} seconds")
    
    # Concatenate chunks with crossfading
    print("Concatenating chunks with crossfading...")
    generated = audio.concatenate(chunks, crossfade_time=mrt.config.crossfade_length)
    
    # Save to file
    print(f"Saving to '{output_file}'...")
    generated.write(output_file)
    
    # Summary
    print("=" * 40)
    print("Demo Complete!")
    print(f"Summary:")
    print(f"   - Model: {mrt._tag}")
    print(f"   - Device: GPU")
    print(f"   - Duration: {generated.num_samples / generated.sample_rate:.1f}s")
    print(f"   - Sample rate: {generated.sample_rate} Hz")
    print(f"   - Channels: {generated.num_channels}")
    print(f"   - Output file: {output_file}")
    print(f"   - Total time: {time.time() - start_time:.1f}s")
    print(f"   - Generation speed: {generated.num_samples / generated.sample_rate / generation_time:.2f}x realtime")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
