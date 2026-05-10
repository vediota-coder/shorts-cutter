"""brand_kernel — внешний фасад для скомпилированного Cython модуля.

Реальная реализация в _kernel.cpython-*.so (после `python setup.py build_ext --inplace`).
"""
from ._kernel import (
    License,
    LicenseError,
    assert_modules_intact,
    encrypt_asset_for_license,
    get_machine_fp,
    kernel_info,
    load_asset_bytes,
    load_brand_template,
    load_license,
    verify_module_integrity,
    verify_watermark_payload,
    watermark_payload,
)

__all__ = [
    "License",
    "LicenseError",
    "load_license",
    "load_brand_template",
    "load_asset_bytes",
    "encrypt_asset_for_license",
    "watermark_payload",
    "verify_watermark_payload",
    "verify_module_integrity",
    "assert_modules_intact",
    "get_machine_fp",
    "kernel_info",
]
