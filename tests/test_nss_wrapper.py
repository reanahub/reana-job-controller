# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Tests for nss_wrapper bootstrap helpers."""

import os
from pathlib import Path

import pytest

from reana_job_controller.nss_wrapper import (
    K8S_USE_SECURITY_CONTEXT_ENV,
    LIBNSS_WRAPPER_PATH_ENV,
    NSS_WRAPPER_GROUP_ENV,
    NSS_WRAPPER_PASSWD_ENV,
    NSSWrapperSetupError,
    WORKFLOW_RUNTIME_GROUP_NAME_ENV,
    WORKFLOW_RUNTIME_USER_GID_ENV,
    WORKFLOW_RUNTIME_USER_NAME_ENV,
    WORKFLOW_RUNTIME_USER_UID_ENV,
    _get_server_command,
    bootstrap_nss_wrapper,
    get_runtime_identity,
    main,
)


@pytest.fixture(autouse=True)
def _restore_environ():
    """Restore process environment mutations performed by bootstrap_nss_wrapper()."""
    original_environ = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_environ)


def test_get_runtime_identity_uses_configured_ids(monkeypatch):
    """Configured UID/GID should be used when security contexts are enabled."""
    monkeypatch.setenv(K8S_USE_SECURITY_CONTEXT_ENV, "True")
    monkeypatch.setenv("CERN_USER", "johndoe")
    monkeypatch.setenv(WORKFLOW_RUNTIME_GROUP_NAME_ENV, "root")
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_UID_ENV, "1000")
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_GID_ENV, "0")

    identity = get_runtime_identity()

    assert identity.user_name == "johndoe"
    assert identity.group_name == "root"
    assert identity.uid == 1000
    assert identity.gid == 0


def test_get_runtime_identity_uses_process_ids_when_security_context_disabled(
    monkeypatch,
):
    """OpenShift-style deployments should derive the real runtime UID/GID."""
    monkeypatch.setenv(K8S_USE_SECURITY_CONTEXT_ENV, "False")
    monkeypatch.delenv("CERN_USER", raising=False)
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_NAME_ENV, "reana")
    monkeypatch.setenv(WORKFLOW_RUNTIME_GROUP_NAME_ENV, "root")
    monkeypatch.setattr("os.getuid", lambda: 43210)
    monkeypatch.setattr("os.getgid", lambda: 54321)

    identity = get_runtime_identity()

    assert identity.user_name == "reana"
    assert identity.group_name == "reana"
    assert identity.uid == 43210
    assert identity.gid == 54321


def test_bootstrap_nss_wrapper_materializes_files_and_sets_env(tmp_path, monkeypatch):
    """Bootstrap should preserve base entries and add the workflow identity."""
    passwd_source = tmp_path / "passwd.source"
    group_source = tmp_path / "group.source"
    passwd_target = tmp_path / "passwd"
    group_target = tmp_path / "group"
    libnss_wrapper = tmp_path / "libnss_wrapper.so"

    passwd_source.write_text("root:x:0:0:root:/root:/bin/bash\n")
    group_source.write_text("root:x:0:\n")
    libnss_wrapper.write_text("placeholder")

    monkeypatch.setattr("reana_job_controller.nss_wrapper.PASSWD_SOURCE", passwd_source)
    monkeypatch.setattr("reana_job_controller.nss_wrapper.GROUP_SOURCE", group_source)
    monkeypatch.setenv(K8S_USE_SECURITY_CONTEXT_ENV, "True")
    monkeypatch.setenv("CERN_USER", "johndoe")
    monkeypatch.setenv(WORKFLOW_RUNTIME_GROUP_NAME_ENV, "root")
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_UID_ENV, "1000")
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_GID_ENV, "0")
    monkeypatch.setenv(NSS_WRAPPER_PASSWD_ENV, str(passwd_target))
    monkeypatch.setenv(NSS_WRAPPER_GROUP_ENV, str(group_target))
    monkeypatch.setenv(LIBNSS_WRAPPER_PATH_ENV, str(libnss_wrapper))
    monkeypatch.setenv("HOME", str(tmp_path / "runtime-home"))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    identity = bootstrap_nss_wrapper()

    assert identity.user_name == "johndoe"
    passwd_contents = passwd_target.read_text()
    group_contents = group_target.read_text()

    assert "root:x:0:0:root:/root:/bin/bash" in passwd_contents
    assert (
        f"johndoe:x:1000:0:johndoe:{tmp_path / 'runtime-home'}:/bin/bash"
        in passwd_contents
    )
    assert "root:x:0:" in group_target.read_text()
    assert (
        sum(line.startswith("johndoe:") for line in passwd_contents.splitlines()) == 1
    )
    assert sum(line.startswith("root:") for line in group_contents.splitlines()) == 1
    assert os.environ["LD_PRELOAD"] == str(libnss_wrapper)


def test_bootstrap_nss_wrapper_preserves_root_group_on_openshift_like_runtime(
    tmp_path, monkeypatch
):
    """Arbitrary runtime GIDs must not rewrite the base root group entry."""
    passwd_source = tmp_path / "passwd.source"
    group_source = tmp_path / "group.source"
    passwd_target = tmp_path / "passwd"
    group_target = tmp_path / "group"
    libnss_wrapper = tmp_path / "libnss_wrapper.so"

    passwd_source.write_text("root:x:0:0:root:/root:/bin/bash\n")
    group_source.write_text("root:x:0:\nusers:x:100:\n")
    libnss_wrapper.write_text("placeholder")

    monkeypatch.setattr("reana_job_controller.nss_wrapper.PASSWD_SOURCE", passwd_source)
    monkeypatch.setattr("reana_job_controller.nss_wrapper.GROUP_SOURCE", group_source)
    monkeypatch.setenv(K8S_USE_SECURITY_CONTEXT_ENV, "False")
    monkeypatch.setenv(WORKFLOW_RUNTIME_GROUP_NAME_ENV, "root")
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_NAME_ENV, "reana")
    monkeypatch.setenv(NSS_WRAPPER_PASSWD_ENV, str(passwd_target))
    monkeypatch.setenv(NSS_WRAPPER_GROUP_ENV, str(group_target))
    monkeypatch.setenv(LIBNSS_WRAPPER_PATH_ENV, str(libnss_wrapper))
    monkeypatch.setenv("HOME", "/home/ubuntu")
    monkeypatch.setattr("os.getuid", lambda: 43210)
    monkeypatch.setattr("os.getgid", lambda: 54321)

    identity = bootstrap_nss_wrapper()
    group_contents = group_target.read_text()

    assert identity.group_name == "reana"
    assert "root:x:0:" in group_contents
    assert "reana:x:54321:" in group_contents
    assert sum(line.startswith("root:") for line in group_contents.splitlines()) == 1


def test_get_runtime_identity_falls_back_to_tmp_home_when_home_is_not_writable(
    tmp_path, monkeypatch
):
    """Use a tmp-backed runtime home when the configured HOME is not writable."""
    fallback_home_root = tmp_path / "fallback-home"
    monkeypatch.setenv(K8S_USE_SECURITY_CONTEXT_ENV, "False")
    monkeypatch.setenv("HOME", "/proc/reana-unwritable-home")
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_NAME_ENV, "reana")
    monkeypatch.setenv(WORKFLOW_RUNTIME_GROUP_NAME_ENV, "root")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr("os.getuid", lambda: 43210)
    monkeypatch.setattr("os.getgid", lambda: 54321)
    monkeypatch.setattr(
        "reana_job_controller.nss_wrapper.FALLBACK_HOME_ROOT",
        fallback_home_root,
    )

    identity = get_runtime_identity()

    assert identity.home == str(fallback_home_root / "43210")


def test_bootstrap_nss_wrapper_prepares_runtime_home_cache_dirs(tmp_path, monkeypatch):
    """Bootstrap should materialize writable HOME, XDG cache, and condor dirs."""
    passwd_source = tmp_path / "passwd.source"
    group_source = tmp_path / "group.source"
    passwd_target = tmp_path / "passwd"
    group_target = tmp_path / "group"
    libnss_wrapper = tmp_path / "libnss_wrapper.so"
    fallback_home_root = tmp_path / "fallback-home"

    passwd_source.write_text("root:x:0:0:root:/root:/bin/bash\n")
    group_source.write_text("root:x:0:\n")
    libnss_wrapper.write_text("placeholder")

    monkeypatch.setattr("reana_job_controller.nss_wrapper.PASSWD_SOURCE", passwd_source)
    monkeypatch.setattr("reana_job_controller.nss_wrapper.GROUP_SOURCE", group_source)
    monkeypatch.setattr(
        "reana_job_controller.nss_wrapper.FALLBACK_HOME_ROOT",
        fallback_home_root,
    )
    monkeypatch.setenv(K8S_USE_SECURITY_CONTEXT_ENV, "False")
    monkeypatch.setenv("HOME", "/proc/reana-unwritable-home")
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_NAME_ENV, "reana")
    monkeypatch.setenv(WORKFLOW_RUNTIME_GROUP_NAME_ENV, "root")
    monkeypatch.setenv(NSS_WRAPPER_PASSWD_ENV, str(passwd_target))
    monkeypatch.setenv(NSS_WRAPPER_GROUP_ENV, str(group_target))
    monkeypatch.setenv(LIBNSS_WRAPPER_PATH_ENV, str(libnss_wrapper))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr("os.getuid", lambda: 43210)
    monkeypatch.setattr("os.getgid", lambda: 54321)

    identity = bootstrap_nss_wrapper()
    home_path = Path(identity.home)

    assert home_path == fallback_home_root / "43210"
    assert home_path.is_dir()
    assert (home_path / ".cache").is_dir()
    assert (home_path / ".condor").is_dir()
    assert os.environ["HOME"] == str(home_path)
    assert os.environ["XDG_CACHE_HOME"] == str(home_path / ".cache")


def test_bootstrap_nss_wrapper_fails_without_library(tmp_path, monkeypatch):
    """Bootstrap should fail fast when the wrapper library is missing."""
    passwd_source = tmp_path / "passwd.source"
    group_source = tmp_path / "group.source"
    passwd_target = tmp_path / "passwd"
    group_target = tmp_path / "group"

    passwd_source.write_text("root:x:0:0:root:/root:/bin/bash\n")
    group_source.write_text("root:x:0:\n")

    monkeypatch.setattr("reana_job_controller.nss_wrapper.PASSWD_SOURCE", passwd_source)
    monkeypatch.setattr("reana_job_controller.nss_wrapper.GROUP_SOURCE", group_source)
    monkeypatch.setenv(K8S_USE_SECURITY_CONTEXT_ENV, "True")
    monkeypatch.setenv("CERN_USER", "johndoe")
    monkeypatch.setenv(WORKFLOW_RUNTIME_GROUP_NAME_ENV, "root")
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_UID_ENV, "1000")
    monkeypatch.setenv(WORKFLOW_RUNTIME_USER_GID_ENV, "0")
    monkeypatch.setenv(NSS_WRAPPER_PASSWD_ENV, str(passwd_target))
    monkeypatch.setenv(NSS_WRAPPER_GROUP_ENV, str(group_target))
    monkeypatch.setenv(
        LIBNSS_WRAPPER_PATH_ENV, str(tmp_path / "missing-libnss_wrapper.so")
    )

    with pytest.raises(NSSWrapperSetupError, match="libnss_wrapper"):
        bootstrap_nss_wrapper()


def test_get_server_command_uses_flask_in_debug(monkeypatch):
    """Debug mode should keep using the Flask development server."""
    monkeypatch.setenv("FLASK_DEBUG", "true")

    assert _get_server_command() == ["flask", "run", "-h", "0.0.0.0"]


def test_get_server_command_uses_uwsgi_when_config_present(tmp_path, monkeypatch):
    """Production mode should use uwsgi when the mounted config is present."""
    uwsgi_config = tmp_path / "uwsgi.ini"
    uwsgi_config.write_text("[uwsgi]\n")
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.setattr(
        "reana_job_controller.nss_wrapper.UWSGI_CONFIG_PATH", uwsgi_config
    )

    assert _get_server_command() == ["uwsgi", "--ini", str(uwsgi_config)]


def test_get_server_command_falls_back_to_flask_without_uwsgi_config(monkeypatch):
    """Standalone runs should fall back to Flask when the uwsgi config is absent."""
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.setattr(
        "reana_job_controller.nss_wrapper.UWSGI_CONFIG_PATH",
        Path("/definitely/missing/uwsgi.ini"),
    )

    assert _get_server_command() == ["flask", "run", "-h", "0.0.0.0"]


def test_main_returns_error_when_execvp_fails(monkeypatch, caplog):
    """CLI entrypoint should log and return non-zero on exec failures."""
    identity = type(
        "Identity",
        (),
        {"user_name": "reana", "uid": 1000, "gid": 0},
    )()
    monkeypatch.setattr(
        "reana_job_controller.nss_wrapper.bootstrap_nss_wrapper", lambda: identity
    )
    monkeypatch.setattr(
        "reana_job_controller.nss_wrapper._get_server_command",
        lambda: ["uwsgi", "--ini", "/tmp/uwsgi.ini"],
    )

    def failing_execvp(_, __):
        raise OSError("missing binary")

    monkeypatch.setattr("os.execvp", failing_execvp)
    caplog.set_level("ERROR")

    assert main() == 1
    assert "Failed to exec uwsgi: missing binary" in caplog.text
