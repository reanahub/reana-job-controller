# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""REANA-Job-Controller application instance."""

import logging
import threading

from reana_job_controller.factory import create_app
from reana_job_controller.k8s import k8s_watch_jobs

JOB_DB = {}

if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(threadName)s - %(levelname)s: %(message)s'
    )

    app = create_app()

    job_event_reader_thread = threading.Thread(target=k8s_watch_jobs,
                                               args=(JOB_DB,))

    job_event_reader_thread.start()

    app.run(debug=True, port=5000,
            host='0.0.0.0')
