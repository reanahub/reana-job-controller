# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Bootstrap nss_wrapper before starting the job controller."""

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)

DEFAULT_GROUP_NAME = "root"
DEFAULT_HOME = "/tmp/reana-job-controller"
DEFAULT_SHELL = "/bin/bash"
DEFAULT_USER_NAME = "reana"
FALLBACK_HOME_ROOT = Path("/tmp/reana-job-controller")
FLASK_DEBUG_VALUES = {"1", "true"}
GROUP_SOURCE = Path("/etc/group")
PASSWD_SOURCE = Path("/etc/passwd")
UWSGI_CONFIG_PATH = Path("/var/reana/uwsgi/uwsgi.ini")

K8S_USE_SECURITY_CONTEXT_ENV = "K8S_USE_SECURITY_CONTEXT"
LIBNSS_WRAPPER_PATH_ENV = "LIBNSS_WRAPPER_PATH"
NSS_WRAPPER_GROUP_ENV = "NSS_WRAPPER_GROUP"
NSS_WRAPPER_PASSWD_ENV = "NSS_WRAPPER_PASSWD"
WORKFLOW_RUNTIME_GROUP_NAME_ENV = "WORKFLOW_RUNTIME_GROUP_NAME"
WORKFLOW_RUNTIME_USER_GID_ENV = "WORKFLOW_RUNTIME_USER_GID"
WORKFLOW_RUNTIME_USER_NAME_ENV = "WORKFLOW_RUNTIME_USER_NAME"
WORKFLOW_RUNTIME_USER_UID_ENV = "WORKFLOW_RUNTIME_USER_UID"


class NSSWrapperSetupError(RuntimeError):
    """Raised when the nss_wrapper runtime contract cannot be fulfilled."""


@dataclass(frozen=True)
class RuntimeIdentity:
    """Identity that the job controller should expose via nss_wrapper."""

    user_name: str
    group_name: str
    uid: int
    gid: int
    home: str
    shell: str


def _get_required_env(name):
    """Get a required environment variable."""
    value = os.getenv(name)
    if not value:
        raise NSSWrapperSetupError(f"Environment variable {name} is not set.")
    return value


def _using_security_context():
    """Return whether Kubernetes security contexts are enabled."""
    return os.getenv(K8S_USE_SECURITY_CONTEXT_ENV, "True").lower() == "true"


def _resolve_runtime_home(uid):
    """Return a writable home directory for the current runtime identity."""
    preferred_home = Path(os.getenv("HOME", DEFAULT_HOME))
    candidate_paths = [preferred_home]
    fallback_home = FALLBACK_HOME_ROOT / str(uid)
    if fallback_home != preferred_home:
        candidate_paths.append(fallback_home)

    for candidate in candidate_paths:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".reana-write-test"
            probe.write_text("")
            probe.unlink()
            return str(candidate)
        except OSError:
            continue

    raise NSSWrapperSetupError(
        "Could not create a writable runtime home directory under "
        f"{preferred_home} or {fallback_home}."
    )


def get_runtime_identity():
    """Resolve the runtime identity for the synthetic NSS entries."""
    user_name = os.getenv("CERN_USER") or os.getenv(
        WORKFLOW_RUNTIME_USER_NAME_ENV, DEFAULT_USER_NAME
    )
    if not user_name:
        raise NSSWrapperSetupError(
            "Could not determine workflow username from CERN_USER "
            f"or {WORKFLOW_RUNTIME_USER_NAME_ENV}."
        )

    if _using_security_context():
        uid = int(_get_required_env(WORKFLOW_RUNTIME_USER_UID_ENV))
        gid = int(_get_required_env(WORKFLOW_RUNTIME_USER_GID_ENV))
        group_name = os.getenv(WORKFLOW_RUNTIME_GROUP_NAME_ENV, DEFAULT_GROUP_NAME)
    else:
        uid = os.getuid()
        gid = os.getgid()
        configured_group_name = os.getenv(
            WORKFLOW_RUNTIME_GROUP_NAME_ENV, DEFAULT_GROUP_NAME
        )
        group_name = (
            user_name
            if configured_group_name == DEFAULT_GROUP_NAME and gid != 0
            else configured_group_name
        )

    return RuntimeIdentity(
        user_name=user_name,
        group_name=group_name,
        uid=uid,
        gid=gid,
        home=_resolve_runtime_home(uid),
        shell=DEFAULT_SHELL,
    )


def _build_passwd_contents(base_contents, identity):
    """Merge the workflow user into passwd contents."""
    desired_entry = (
        f"{identity.user_name}:x:{identity.uid}:{identity.gid}:"
        f"{identity.user_name}:{identity.home}:{identity.shell}"
    )
    desired_uid = str(identity.uid)
    merged_lines = []
    replaced = False
    for line in base_contents.splitlines():
        fields = line.split(":")
        if len(fields) >= 7 and (
            fields[0] == identity.user_name or fields[2] == desired_uid
        ):
            if not replaced:
                merged_lines.append(desired_entry)
                replaced = True
            continue
        merged_lines.append(line)
    if not replaced:
        merged_lines.append(desired_entry)
    return "\n".join(merged_lines) + "\n"


def _build_group_contents(base_contents, identity):
    """Merge the workflow group into group contents."""
    desired_entry = f"{identity.group_name}:x:{identity.gid}:"
    desired_gid = str(identity.gid)
    merged_lines = []
    replaced = False
    for line in base_contents.splitlines():
        fields = line.split(":")
        if len(fields) >= 4 and fields[2] == desired_gid:
            if not replaced:
                merged_lines.append(desired_entry)
                replaced = True
            continue
        merged_lines.append(line)
    if not replaced:
        merged_lines.append(desired_entry)
    return "\n".join(merged_lines) + "\n"


def bootstrap_nss_wrapper():
    """Materialize passwd/group files and set nss_wrapper environment."""
    passwd_target = Path(_get_required_env(NSS_WRAPPER_PASSWD_ENV))
    group_target = Path(_get_required_env(NSS_WRAPPER_GROUP_ENV))
    library_path = Path(_get_required_env(LIBNSS_WRAPPER_PATH_ENV))
    identity = get_runtime_identity()
    home_path = Path(identity.home)
    cache_path = home_path / ".cache"
    condor_path = home_path / ".condor"

    if not library_path.is_file():
        raise NSSWrapperSetupError(
            f"libnss_wrapper shared library does not exist: {library_path}"
        )

    try:
        home_path.mkdir(parents=True, exist_ok=True)
        cache_path.mkdir(parents=True, exist_ok=True)
        condor_path.mkdir(parents=True, exist_ok=True)
        passwd_target.parent.mkdir(parents=True, exist_ok=True)
        group_target.parent.mkdir(parents=True, exist_ok=True)
        passwd_contents = _build_passwd_contents(
            PASSWD_SOURCE.read_text(), identity=identity
        )
        group_contents = _build_group_contents(
            GROUP_SOURCE.read_text(), identity=identity
        )
        passwd_target.write_text(passwd_contents)
        group_target.write_text(group_contents)
    except OSError as exc:
        raise NSSWrapperSetupError(
            "Failed to materialize nss_wrapper passwd/group files under "
            f"{passwd_target.parent}: {exc}"
        ) from exc

    os.environ["LD_PRELOAD"] = str(library_path)
    os.environ["NSS_WRAPPER_PASSWD"] = str(passwd_target)
    os.environ["NSS_WRAPPER_GROUP"] = str(group_target)
    os.environ["USER"] = identity.user_name
    os.environ["HOME"] = identity.home
    os.environ["XDG_CACHE_HOME"] = str(cache_path)

    return identity


def _get_server_command():
    """Select the job-controller server command for the current runtime."""
    flask_debug = os.getenv("FLASK_DEBUG", "").lower() in FLASK_DEBUG_VALUES
    if flask_debug:
        return ["flask", "run", "-h", "0.0.0.0"]
    if UWSGI_CONFIG_PATH.is_file():
        return ["uwsgi", "--ini", str(UWSGI_CONFIG_PATH)]
    LOGGER.info(
        "uwsgi config %s was not found, falling back to the Flask development "
        "server.",
        UWSGI_CONFIG_PATH,
    )
    return ["flask", "run", "-h", "0.0.0.0"]


def main():
    """Bootstrap nss_wrapper and exec the selected job-controller server."""
    logging.basicConfig(level=logging.INFO)
    try:
        identity = bootstrap_nss_wrapper()
    except NSSWrapperSetupError as exc:
        LOGGER.error("Failed to bootstrap nss_wrapper: %s", exc)
        return 1

    LOGGER.info(
        "Starting job controller with nss_wrapper identity %s (%s:%s).",
        identity.user_name,
        identity.uid,
        identity.gid,
    )
    command = _get_server_command()
    LOGGER.info("Starting job controller via %s.", command[0])
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        LOGGER.error("Failed to exec %s: %s", command[0], exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
