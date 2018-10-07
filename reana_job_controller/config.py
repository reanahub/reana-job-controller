# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Flask application configuration."""

import os

MAX_JOB_RESTARTS = 3
"""Number of retries for a job before considering it as failed."""

SHARED_FS_MAPPING = {
    'MOUNT_SOURCE_PATH': os.getenv("SHARED_VOLUME_PATH_ROOT", '/reana'),
    # Root path in the underlying shared file system to be mounted inside
    # jobs.
    'MOUNT_DEST_PATH': os.getenv("SHARED_VOLUME_PATH", '/reana'),
    # Mount path for the shared file system volume inside jobs.
}
"""Mapping from the shared file system backend to the job file system."""
