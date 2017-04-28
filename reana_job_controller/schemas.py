#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017 CERN.
#
# REANA is free software; you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# REANA is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# REANA; if not, write to the Free Software Foundation, Inc., 59 Temple Place,
# Suite 330, Boston, MA 02111-1307, USA.
#
# In applying this license, CERN does not waive the privileges and immunities
# granted to it by virtue of its status as an Intergovernmental Organization or
# submit itself to any jurisdiction.

"""REANA Job Controller models."""

import uuid

from marshmallow import Schema, fields, pre_load


class Job(Schema):
    """Job model."""

    cmd = fields.Str(required=True)
    docker_img = fields.Str(required=True)
    experiment = fields.Str(required=True)
    job_id = fields.Str(required=True)
    max_restart_count = fields.Int(required=True)
    restart_count = fields.Int(required=True)
    status = fields.Str(required=True)
    cvmfs_mounts = fields.List(fields.String(), required=True)


class JobRequest(Schema):
    """Job request model."""

    job_id = fields.UUID()
    cmd = fields.Str(missing='')
    docker_img = fields.Str(required=True)
    experiment = fields.Str(required=True)
    cvmfs_mounts = fields.List(fields.String(), missing=[])
    env_vars = fields.Dict(missing={})
    shared_file_system = fields.Bool(missing=True)

    @pre_load
    def make_id(self, data):
        """Generate UUID for new Jobs."""
        data['job_id'] = uuid.uuid4()
        return data
