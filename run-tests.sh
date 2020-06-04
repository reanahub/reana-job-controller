#!/bin/bash
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

COMPONENT_NAME=reana-job-controller
DOCKER_IMAGE_NAME=reanahub/$COMPONENT_NAME
PLATFORM="$(python -c 'import platform; print(platform.system())')"

RUN_TESTS="pydocstyle reana_job_controller &&
isort -rc -c -df **/*.py &&
check-manifest --ignore '.travis-*' &&
FLASK_APP=reana_job_controller/app.py flask openapi create openapi.json  &&
diff -q openapi.json docs/openapi.json &&
sphinx-build -qnN docs docs/_build/html &&
python setup.py test &&
rm openapi.json || exit 1"

case $PLATFORM in
Darwin*)
    # Tests are run inside the docker container because there is
    # no HTCondor Python package for MacOS
    echo "==> Running tests inside $DOCKER_IMAGE_NAME Docker image ..."
    docker build -t $DOCKER_IMAGE_NAME .
    RUN_TESTS_INSIDE_DOCKER="
    cd $COMPONENT_NAME &&
    apt update &&
    apt install git -y && # Needed by check-manifest
    pip install --force-reinstall ../reana-commons ../reana-db ../pytest-reana &&
    pip install .[all] && # Install test dependencies
    eval $RUN_TESTS"
    docker run -v $(pwd)/..:/code -ti $DOCKER_IMAGE_NAME bash -c "eval $RUN_TESTS_INSIDE_DOCKER"
    ;;
*)
    echo "==> Running tests locally ..."
    eval $RUN_TESTS
    # Test Docker build?
    if [[ ! "$@" = *"--include-docker-tests"* ]]; then
        exit 0
    fi
    docker build -t $DOCKER_IMAGE_NAME .
    ;;
esac
