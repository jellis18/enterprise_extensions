#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from setuptools import setup, find_packages, Extension
from Cython.Build import cythonize
import os
import numpy
import platform

with open("README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()

requirements = [
    "numpy>=1.16.3",
    "scipy>=1.2.0",
    "Cython>=0.28.5",
    "ephem>=3.7.6.0",
    "healpy>=1.14.0",
    "scikit-sparse>=0.4.5",
    "pint-pulsar>=0.8.2",
    "libstempo>=2.4.0",
    "enterprise-pulsar>=3.1.0",
    "emcee",
    "ptmcmcsampler",
]

test_requirements = [
    "pytest",
]

if platform.system() == "Darwin":
    extra_compile_args = ["-O2", "-Xpreprocessor", "-fopenmp", "-fno-wrapv"]
    extra_link_args = ["-liomp5"] if os.getenv("NO_MKL", 0) == 0 else ["-lomp"]
else:
    extra_compile_args = ["-O2", "-fopenmp", "-fno-wrapv"]
    extra_link_args = ["-liomp5"]


ext_modules = [
    Extension(
        "enterprise_extensions.outlier.jitterext",
        ["./enterprise_extensions/outlier/jitterext.pyx"],
        include_dirs=[numpy.get_include()],
        extra_compile_args=["-O2"],
    ),
    Extension(
        "enterprise_extensions.outlier.choleskyext_omp",
        ["./enterprise_extensions/outlier/choleskyext_omp.pyx"],
        include_dirs=[numpy.get_include()],
        extra_link_args=extra_link_args,
        extra_compile_args=extra_compile_args,
    ),
]

# Extract version
def get_version():
    with open("enterprise_extensions/models.py") as f:
        for line in f.readlines():
            if "__version__" in line:
                return line.split('"')[1]


setup(
    name="enterprise_extensions",
    version=get_version(),
    description="Extensions, model shortcuts, and utilities for the enterprise PTA analysis framework.",
    long_description=readme + "\n\n" + history,
    classifiers=[
        "Topic :: Scientific/Engineering :: Astronomy",
        "Topic :: Scientific/Engineering :: Physics",
        "Topic :: Scientific/Engineering :: Mathematics",
        "Intended Audience :: Science/Research",
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    keywords="gravitational-wave, black-hole binary, pulsar-timing arrays",
    url="https://github.com/stevertaylor/enterprise_extensions",
    author="Stephen R. Taylor, Paul T. Baker, Jeffrey S. Hazboun, Sarah Vigeland",
    author_email="srtaylor@caltech.edu",
    license="MIT",
    packages=[
        "enterprise_extensions",
        "enterprise_extensions.frequentist",
        "enterprise_extensions.chromatic",
        "enterprise_extensions.outlier",
    ],
    package_data={
        "enterprise_extensions.chromatic": [
            "ACE_SWEPAM_daily_proton_density_1998_2018_MJD_cm-3.txt"
        ]
    },
    ext_modules=cythonize(ext_modules),
    test_suite="tests",
    tests_require=test_requirements,
    install_requires=requirements,
    include_package_data=True,
    zip_safe=False,
)
