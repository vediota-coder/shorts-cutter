"""Сборка brand_kernel: .pyx → .so

Использование:
    python setup.py build_ext --inplace

После: импортируется через `from brand_kernel import _kernel`.
Исходник .pyx в дистрибутив не входит — клиент получает только .so.
"""
from setuptools import Extension, setup
from Cython.Build import cythonize


extensions = [
    Extension(
        "brand_kernel._kernel",
        sources=["brand_kernel/_kernel.pyx"],
    ),
]

setup(
    name="brand_kernel",
    version="0.1.0",
    packages=["brand_kernel"],
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "embedsignature": False,
        },
    ),
    install_requires=["cryptography>=42.0"],
    zip_safe=False,
)
