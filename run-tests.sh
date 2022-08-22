#!/bin/bash
#
# This file is part of REANA.
# Copyright (C) 2017, 2018, 2020, 2021, 2022 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

# Quit on errors
set -o errexit

# Quit on unbound symbols
set -o nounset

COMPONENT_NAME=reana-job-controller
DOCKER_IMAGE_NAME=reanahub/$COMPONENT_NAME
PLATFORM="$(python -c 'import platform; print(platform.system())')"

# Verify that db container is running before continuing
_check_ready () {
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

_db_check () {
    docker exec --user postgres postgres__reana-job-controller bash -c "pg_isready" &>/dev/null;
}

clean_old_db_container () {
    OLD="$(docker ps --all --quiet --filter=name=postgres__reana-job-controller)"
    if [ -n "$OLD" ]; then
        echo '==> [INFO] Cleaning old DB container...'
        docker stop postgres__reana-job-controller
    fi
}

start_db_container () {
    echo '==> [INFO] Starting DB container...'
    docker run --rm --name postgres__reana-job-controller -p 5432:5432 -e POSTGRES_PASSWORD=mysecretpassword -d postgres:12.10
    _check_ready "Postgres" _db_check
    db_container_ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' postgres__reana-job-controller)
    export REANA_SQLALCHEMY_DATABASE_URI=postgresql+psycopg2://postgres:mysecretpassword@$db_container_ip/postgres
}

stop_db_container () {
    echo '==> [INFO] Stopping DB container...'
    docker stop postgres__reana-job-controller
}

check_script () {
    shellcheck run-tests.sh
}

check_pydocstyle () {
    pydocstyle reana_job_controller
}

check_black () {
    black --check .
}

check_flake8 () {
    flake8 .
}

check_openapi_spec () {
    FLASK_APP=reana_job_controller/app.py flask openapi create openapi.json
    diff -q -w openapi.json docs/openapi.json
    rm openapi.json
}

check_manifest () {
    check-manifest
}

check_sphinx () {
    sphinx-build -qnN docs docs/_build/html
}

check_pytest () {
    clean_old_db_container
    start_db_container
    python setup.py test
    stop_db_container
}

check_dockerfile () {
    docker run -i --rm hadolint/hadolint:v1.18.2 < Dockerfile
}

check_docker_build () {
    docker build -t $DOCKER_IMAGE_NAME .
}

check_all () {
    check_script
    check_pydocstyle
    check_black
    check_flake8
    check_openapi_spec
    check_manifest
    check_sphinx
}

check_all_darwin () {
    # Tests are run inside the docker container because there is
    # no HTCondor Python package for MacOS
    check_dockerfile
    check_docker_build
    clean_old_db_container
    start_db_container
    RUN_TESTS_INSIDE_DOCKER="
    cd $COMPONENT_NAME &&
    apt update && apt-get -y install libkrb5-dev git shellcheck  &&
    pip install -r requirements.txt &&
    pip install -e .[all] && # Install test dependencies
    pip install black &&
    pip install flake8 &&
    pip install pydocstyle &&
    pip install check-manifest &&
    export REANA_SQLALCHEMY_DATABASE_URI=$REANA_SQLALCHEMY_DATABASE_URI &&
    ./run-tests.sh --check-all &&
    python setup.py test"
    docker run -v "$(pwd)"/..:/code -ti $DOCKER_IMAGE_NAME bash -c "eval $RUN_TESTS_INSIDE_DOCKER"
    stop_db_container
}

if [ $# -eq 0 ]; then
    case $PLATFORM in
    Darwin*) check_all_darwin;;
    *)
        check_all
        check_pytest
        check_dockerfile
        check_docker_build
    ;;
    esac
    exit 0
fi

for arg in "$@"
do
    case $arg in
        --check-shellscript) check_script;;
        --check-pydocstyle) check_pydocstyle;;
        --check-black) check_black;;
        --check-flake8) check_flake8;;
        --check-openapi-spec) check_openapi_spec;;
        --check-manifest) check_manifest;;
        --check-sphinx) check_sphinx;;
        --check-pytest) check_pytest;;
        --check-all) check_all;;
        --check-dockerfile) check_dockerfile;;
        --check-docker-build) check_docker_build;;
        *)
    esac
done
