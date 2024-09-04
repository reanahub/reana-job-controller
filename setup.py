# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller."""

from __future__ import absolute_import, print_function

import os
import re

from setuptools import find_packages, setup

readme = open("README.md").read()
history = open("CHANGELOG.md").read()


extras_require = {
    "debug": [
        "wdb",
        "ipdb",
        "Flask-DebugToolbar",
    ],
    "docs": [
        "myst-parser",
        "Sphinx>=1.5.1",
        "sphinx-rtd-theme>=0.1.9",
        "sphinxcontrib-httpdomain>=1.5.0",
        "sphinxcontrib-openapi>=0.8.0",
        "sphinxcontrib-redoc>=1.5.1",
    ],
    "htcondor": [
        "htcondor>=9.0.17",
    ],
    "tests": [
        "pytest-reana>=0.95.0a4,<0.96.0",
    ],
    "ssh": [
        "paramiko[gssapi]>=3.0.0",
        "gssapi==1.8.2",  # matches version in Dockerfile
    ],
}

# Python tests need SSH dependencies for imports
extras_require["tests"].extend(extras_require["ssh"])

extras_require["all"] = []
for key, reqs in extras_require.items():
    if ":" == key[0]:
        continue
    extras_require["all"].extend(reqs)

install_requires = [
    # apispec>=4.0 drops support for marshmallow<3
    "apispec[yaml]>=3.0,<4.0",
    "apispec-webframeworks",
    "Flask>=2.1.1,<2.3.0",  # same upper pin as invenio-base/reana-server
    "Werkzeug>=2.1.0,<2.3.0",  # same upper pin as invenio-base
    "jinja2<3.1.0",
    "fs>=2.0",
    "marshmallow>2.13.0,<3.0.0",  # same upper pin as reana-server
    "reana-commons[kubernetes] @ git+https://github.com/reanahub/reana-commons.git@0.95.0a4",
    "reana-db>=0.95.0a4,<0.96.0",
    "retrying>=1.3.3",
]

packages = find_packages()


# Get the version string. Cannot be done with import!
with open(os.path.join("reana_job_controller", "version.py"), "rt") as f:
    version = re.search(r'__version__\s*=\s*"(?P<version>.*)"\n', f.read()).group(
        "version"
    )

setup(
    name="reana-job-controller",
    version=version,
    description=__doc__,
    long_description=readme + "\n\n" + history,
    long_description_content_type="text/markdown",
    author="REANA",
    author_email="info@reana.io",
    url="https://github.com/reanahub/reana-job-controller",
    packages=[
        "reana_job_controller",
    ],
    zip_safe=False,
    entry_points={
        "flask.commands": [
            "openapi = reana_job_controller.cli:openapi",
        ],
    },
    python_requires=">=3.8",
    extras_require=extras_require,
    install_requires=install_requires,
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
)
