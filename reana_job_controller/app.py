# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2020, 2021 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller application instance."""

import logging

from reana_job_controller.factory import create_app
from reana_job_controller.job_db import JOB_DB

app = create_app(JOB_DB)

if __name__ == "__main__":
    app.run(host="0.0.0.0")
