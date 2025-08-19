#!/bin/bash

# Ensure dependencies are installed
echo "Installing dependencies..."
pip install -r requirements.txt

# Run the pipeline
echo "Running document analyst pipeline..."
python3 src/main.py
