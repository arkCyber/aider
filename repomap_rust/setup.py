from setuptools import setup
from setuptools_rust import Binding, RustExtension

setup(
    name="repomap_rust",
    version="0.1.0",
    rust_extensions=[
        RustExtension(
            "repomap_rust.repomap_rust",
            binding=Binding.PyO3,
            path="Cargo.toml",
        ),
    ],
    zip_safe=False,
    install_requires=["setuptools-rust"],
)
