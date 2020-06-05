#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Click command-line interface for REANA Job Controller."""

import io
import json

import click
from flask import current_app
from flask.cli import with_appcontext

from .spec import build_openapi_spec


@click.group()
def openapi():
    """Openapi management commands."""


@openapi.command()
@click.argument("output", type=click.File("w"))
@with_appcontext
def create(output):
    """Generate OpenAPI file."""
    spec = build_openapi_spec()
    output.write(json.dumps(spec, indent=2, sort_keys=True))
    if not isinstance(output, io.TextIOWrapper):
        click.echo(
            click.style(
                "OpenAPI specification written to {}".format(output.name), fg="green"
            )
        )
