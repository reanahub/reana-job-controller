#!/bin/bash
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2019, 2020 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

# Quit on errors
set -o errexit

# Quit on unbound symbols
set -o nounset

# Verify that db container is running before continuing
_check_ready() {
    RETRIES=40
    while ! $2
    do
        echo "==> [INFO] Waiting for $1, $((RETRIES--)) remaining attempts..."
        sleep 2
        if [ $RETRIES -eq 0 ]
        then
            echo "==> [ERROR] Couldn't reach $1"
            exit 1
        fi
    done
}

_db_check() {
    docker exec --user postgres postgres__reana-job-controller bash -c "pg_isready" &>/dev/null;
}

clean_old_db_container() {
    OLD="$(docker ps --all --quiet --filter=name=postgres__reana-job-controller)"
    if [ -n "$OLD" ]; then
        echo '==> [INFO] Cleaning old DB container...'
        docker stop postgres__reana-job-controller
    fi
}

start_db_container() {
    echo '==> [INFO] Starting DB container...'
    docker run --rm --name postgres__reana-job-controller -p 5432:5432 -e POSTGRES_PASSWORD=mysecretpassword -d postgres:9.6.2
    _check_ready "Postgres" _db_check
}

stop_db_container() {
    echo '==> [INFO] Stopping DB container...'
    docker stop postgres__reana-job-controller
}

check_black() {
    echo "echo '==> [INFO] Checking Black compliance...'"
    echo "black --check ."
}

COMPONENT_NAME=reana-job-controller
DOCKER_IMAGE_NAME=reanahub/$COMPONENT_NAME
PLATFORM="$(python -c 'import platform; print(platform.system())')"

clean_old_db_container
start_db_container
db_container_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' postgres__reana-job-controller)
SQLALCHEMY_URI=postgresql+psycopg2://postgres:mysecretpassword@$db_container_ip/postgres

RUN_TESTS="pydocstyle reana_job_controller &&
$(check_black) &&
check-manifest --ignore '.travis-*' &&
FLASK_APP=reana_job_controller/app.py flask openapi create openapi.json  &&
diff -q openapi.json docs/openapi.json &&
sphinx-build -qnN docs docs/_build/html &&
REANA_SQLALCHEMY_DATABASE_URI=$SQLALCHEMY_URI python setup.py test &&
rm openapi.json || exit 1"

case $PLATFORM in
Darwin*)
    # Tests are run inside the docker container because there is
    # no HTCondor Python package for MacOS
    echo "==> [INFO] Running tests inside $DOCKER_IMAGE_NAME Docker image ..."
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
    echo "==> [INFO] Running tests locally ..."
    eval $RUN_TESTS
    # Test Docker build?
    if [[ ! "$@" = *"--include-docker-tests"* ]]; then
        exit 0
    fi
    docker build -t $DOCKER_IMAGE_NAME .
    ;;
esac

stop_db_container
echo '==> [INFO] All tests passed! ✅'
