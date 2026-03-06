#!/usr/bin/env python3
"""
Matrix statistics tool.

Generates a random NxN matrix using numpy and prints key statistics.
Requires: pip install numpy

Usage: matrix_stats.py <size>
  size: integer dimension of the square matrix (e.g. 4)
"""
import sys

import numpy as np


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <size>")
        sys.exit(1)

    try:
        n = int(sys.argv[1])
        if n < 1:
            raise ValueError
    except ValueError:
        print("Error: size must be a positive integer")
        sys.exit(1)

    rng = np.random.default_rng(seed=42)
    matrix = rng.integers(1, 100, size=(n, n))
    eigenvalues = np.linalg.eigvals(matrix).real

    print(f"Matrix ({n}x{n}):")
    print(matrix)
    print(f"Sum: {int(matrix.sum())}")
    print(f"Mean: {matrix.mean():.2f}")
    print(f"Max: {int(matrix.max())}")
    print(f"Min: {int(matrix.min())}")
    print(f"Largest eigenvalue: {max(eigenvalues):.2f}")


if __name__ == "__main__":
    main()
