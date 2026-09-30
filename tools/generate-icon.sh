#!/bin/bash
# Generate Android app icon PNGs from SVG source
# Usage: ./generate-icon.sh [input.svg] [output_dir]

set -euo pipefail

INPUT="${1:-translate-app-icon-md3.svg}"
OUTDIR="${2:-mipmap}"

if [[ ! -f "$INPUT" ]]; then
    echo "Error: $INPUT not found"
    exit 1
fi

# DPI → size mapping
declare -A SIZES=(
    [mdpi]=48
    [hdpi]=72
    [xhdpi]=96
    [xxhdpi]=144
    [xxxhdpi]=192
)

for dpi in "${!SIZES[@]}"; do
    SIZE="${SIZES[$dpi]}"
    DIR="$OUTDIR/$dpi"
    mkdir -p "$DIR"
    python3 -c "
import cairosvg
cairosvg.svg2png(url='$INPUT', write_to='$DIR/ic_launcher.png', output_width=$SIZE, output_height=$SIZE)
"
    echo "$dpi: $SIZE×$SIZE → $DIR/ic_launcher.png ($(du -h "$DIR/ic_launcher.png" | cut -f1))"
done

echo "Done. Total files: $(find "$OUTDIR" -name '*.png' | wc -l)"
