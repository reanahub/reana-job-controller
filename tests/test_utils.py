# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

import logging
import pytest

from reana_job_controller.utils import MultilineFormatter

"""REANA-Job-Controller utils tests."""


@pytest.mark.parametrize(
    "message,expected_output",
    [
        (
            "test",
            "name | INFO | test",
        ),
        (
            "test\n",
            "name | INFO | test",
        ),
        (
            "test\ntest",
            "name | INFO | test\nname | INFO | test",
        ),
        (
            "test\ntest\n\n\n",
            "name | INFO | test\nname | INFO | test\nname | INFO | \nname | INFO |",
        ),
        (
            "   test\ntest   ",
            "name | INFO |    test\nname | INFO | test",
        ),
        (
            "   t e s\tt\n     t e s t   ",
            "name | INFO |    t e s\tt\nname | INFO |      t e s t",
        ),
    ],
)
def test_multiline_formatter_format(message, expected_output):
    """Test MultilineFormatter formatting."""
    formatter = MultilineFormatter("%(name)s | " "%(levelname)s | %(message)s")
    assert (
        formatter.format(
            logging.LogRecord(
                "name",
                logging.INFO,
                "pathname",
                1,
                message,
                None,
                None,
            ),
        )
        == expected_output
    )
