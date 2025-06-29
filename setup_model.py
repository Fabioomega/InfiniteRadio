#!/usr/bin/env python3
"""
Model Setup Script for Magenta RT

This script pre-downloads and initializes the Magenta RT model
so it's cached and ready for use. Run this during Docker build
to avoid downloading models every time the container starts.
"""

import time
from magenta_rt import system

def setup_model():
    print("Setting up Magenta RT model...")
    print("=" * 50)
    print("This will download and cache the model files")
    print("   (This happens once during Docker build)")
    
    start_time = time.time()
    
    try:
        # Initialize the model - this triggers all downloads
        print("Initializing MagentaRT...")
        mrt = system.MagentaRT(
            tag="base",           # Use base model
            device="gpu",         # Configure for GPU
            skip_cache=False,     # Use cache
            lazy=False           # Load immediately
        )
        
        init_time = time.time() - start_time
        print(f"Model setup complete in {init_time:.1f} seconds")
        
        # Test style embedding to ensure everything works
        print("Testing style embedding...")
        style = mrt.embed_style("test")
        print("Style embedding test successful")
        
        print("=" * 50)
        print("Model setup successful!")
        print("   All model files are now cached and ready to use.")
        
    except Exception as e:
        print(f"ERROR: Model setup failed: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    setup_model() 
