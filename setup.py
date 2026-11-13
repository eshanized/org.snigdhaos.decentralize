#!/usr/bin/env python3
"""
Setup script for Snigdha OS Release Mirroring.
SPDX-License-Identifier: GPL-3.0-or-later
"""

from setuptools import setup, find_packages

setup(
    name="snigdhaos-release-mirror",
    version="1.0.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "release-mirror=release_mirror.cli:main",
        ],
    },
)
