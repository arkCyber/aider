# Rust-Accelerated RepoMap Build Instructions

## Prerequisites

- Rust toolchain (rustc, cargo)
- Python 3.10+
- setuptools-rust

## Installation

### Install Rust

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

### Build the Rust Extension

```bash
cd /Users/arksong/aider/repomap_rust
pip install setuptools-rust
python3.10 setup.py build
python3.10 setup.py install
```

### Alternative: Use maturin (recommended)

```bash
pip install maturin
cd /Users/arksong/aider/repomap_rust
maturin develop
```

## Verification

```bash
python3.10 -c "from repomap_rust import repomap_rust; print('Rust module loaded successfully')"
```

## Performance Testing

Run the benchmark script to compare Python vs Rust performance:

```bash
cd /Users/arksong/aider
python3.10 test_rust_repomap_performance.py
```

## Troubleshooting

### Rust not found
Install Rust: https://rustup.rs/

### Python binding errors
Ensure setuptools-rust is installed: `pip install setuptools-rust`

### Compilation errors
Ensure Rust toolchain is up to date: `rustup update`

## Fallback

If Rust module fails to load, the Python implementation will be used automatically.
