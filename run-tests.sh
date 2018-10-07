#!/bin/sh
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

pydocstyle reana_job_controller && \
isort -rc -c -df **/*.py && \
check-manifest --ignore ".travis-*" && \
FLASK_APP=reana_job_controller/app.py flask openapi create openapi.json  && \
diff -q openapi.json docs/openapi.json && \
sphinx-build -qnN docs docs/_build/ && \
python setup.py test && \
sphinx-build -qnN -b doctest docs docs/_build/doctest && \
rm openapi.json && \
docker build -t reanahub/reana-job-controller .
