#!/bin/bash
# EC2 setup script for LIDAR analysis environment
# Run once after instance launch: bash setup_ec2.sh
set -euo pipefail

echo "=== LIDAR EC2 Setup ==="

# --- System updates + git ---
sudo dnf update -y -q
sudo dnf install -y -q git

# --- Miniforge (conda) ---
echo "Installing Miniforge..."
curl -sLo /tmp/miniforge.sh \
  https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
rm /tmp/miniforge.sh

# Add to shell
echo 'export PATH="$HOME/miniforge3/bin:$PATH"' >> ~/.bashrc
source "$HOME/miniforge3/etc/profile.d/conda.sh"
conda init bash

# --- LIDAR conda environment ---
echo "Creating lidar conda environment..."
conda create -n lidar -y -q -c conda-forge \
  python=3.11 \
  pdal \
  python-pdal \
  numpy \
  scipy \
  scikit-learn \
  geopandas \
  shapely \
  pyproj \
  rasterio \
  folium \
  requests \
  typer \
  rich

# pysheds via pip (conda-forge version pulls numba; pip <0.3 avoids it on all platforms)
conda run -n lidar pip install -q "pysheds<0.3"

echo "pdal version: $(pdal --version 2>&1 | head -1)"
echo "python-pdal: $(python -c 'import pdal; print(pdal.__version__)')"

# --- Clone repo ---
echo "Cloning repo..."
git clone https://github.com/drkatz44/claudecode.git ~/claudecode

# --- Output + cache dirs ---
mkdir -p ~/.cache/lidar/parcels ~/claudecode/projects/lidar/output

# --- Convenience aliases ---
cat >> ~/.bashrc << 'EOF'

# LIDAR shortcuts
alias lidar-env='conda activate lidar'
alias lidar='conda activate lidar && cd ~/claudecode/projects/lidar'
alias lidar-analyze='conda activate lidar && cd ~/claudecode/projects/lidar && uv run lidar analyze'
EOF

echo ""
echo "=== Setup complete ==="
echo "Start a new shell or run: source ~/.bashrc"
echo "Then: conda activate lidar"
echo "      cd ~/claudecode/projects/lidar"
echo "      python -m lidar.cli analyze"
