#!/usr/bin/env python3
"""CLI interface for HabiTree 3D Generator Tool.

Usage examples:
    python3 cli.py --style zen_bonsai --pieces 30 --seed 42
    python3 cli.py --style sakura --pieces 50 --seed 108
    python3 cli.py --style ghibli_fruit --pieces 14 --seed 7
    python3 cli.py --style autumn_maple --pieces 100 --seed 999
"""

import argparse
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from generator import generate_habit_tree

def main():
    parser = argparse.ArgumentParser(description="Procedural 3D Habit Tracker Tree Generator")
    parser.add_argument("--style", choices=["zen_bonsai", "sakura", "ghibli_fruit", "autumn_maple", "geometric"],
                        default="zen_bonsai", help="Aesthetic style of tree")
    parser.add_argument("--pieces", type=int, default=30, help="Total number of interlocking habit day pieces (14 to 100)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for procedural organic variations")
    parser.add_argument("--output", type=str, default=None, help="Custom output directory (defaults to tools/habitree/output/)")

    args = parser.parse_args()
    
    out_dir = args.output or os.path.join(BASE_DIR, "output")
    manifest = generate_habit_tree(style=args.style, piece_count=args.pieces, seed=args.seed, output_dir=out_dir)
    
    print("\n--- GENERATION SUMMARY ---")
    print(f"Style:           {manifest['style']}")
    print(f"Piece Count:     {manifest['piece_count']} pieces (+ 1 Base Planter)")
    print(f"Total Volume:    {manifest['total_volume_cm3']} cm³")
    print(f"Estimated Mass:  {manifest['estimated_mass_grams']} grams (15% gyroid infill)")
    print(f"Plates Created:  {len(manifest['plates'])} Bambu Lab A1 plates")
    for p in manifest['plates']:
        print(f"  - {p['name']}: {p['filename']} ({p['parts_count']} parts, {p['dimensions']})")
    print(f"\nFiles generated in: {out_dir}")
    print("(Note: The output/ directory is ignored by git to keep your repository clean!)")

if __name__ == "__main__":
    main()
