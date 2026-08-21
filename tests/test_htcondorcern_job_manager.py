# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2026 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Tests for the CERN HTCondor job manager."""

import logging
import os
from unittest import mock

import pytest

classad = pytest.importorskip("classad2")
htcondor = pytest.importorskip("htcondor2")

from reana_commons.k8s.secrets import Secret, UserSecrets  # noqa: E402
from reana_job_controller import htcondorcern_job_manager  # noqa: E402
from reana_job_controller import job_monitor  # noqa: E402


@pytest.fixture
def manager_dependencies():
    """Patch the heavy dependencies of the HTCondor manager constructor."""
    mock_workflow = mock.MagicMock()
    mock_workflow.get_full_workflow_name.return_value = "wf"
    with mock.patch.object(
        htcondorcern_job_manager.HTCondorJobManagerCERN,
        "_get_workflow",
        return_value=mock_workflow,
    ), mock.patch.object(htcondorcern_job_manager, "initialize_krb5_token"):
        yield


@pytest.fixture
def manager(manager_dependencies):
    """Construct an HTCondor manager with its external dependencies patched."""
    return htcondorcern_job_manager.HTCondorJobManagerCERN(
        docker_img="img",
        cmd="ls",
        env_vars={},
        workflow_uuid="uuid",
        workflow_workspace="/data",
        job_name="job",
        htcondor_max_runtime="3600",
    )


@pytest.fixture
def captured_submit(manager_dependencies):
    """Patch ``execute()``'s side effects and capture the submit description.

    Returns a builder ``submit(**kwargs)`` that constructs the manager
    with the given kwargs, calls ``execute()``, and returns the
    ``htcondor2.Submit`` object that the manager would send to the schedd.
    """
    captured = {}

    def fake_executor_submit(_fn, submit):
        captured["submit"] = submit
        future = mock.MagicMock()
        future.result.return_value = "cluster123"
        return future

    fake_app = mock.MagicMock()
    fake_app.htcondor_executor.submit.side_effect = fake_executor_submit

    Manager = htcondorcern_job_manager.HTCondorJobManagerCERN
    with mock.patch.object(
        htcondorcern_job_manager, "current_app", fake_app
    ), mock.patch.object(htcondorcern_job_manager.os, "chdir"), mock.patch.object(
        Manager, "_format_arguments", return_value="echo|base64 -d"
    ), mock.patch.object(
        Manager, "_prepare_file_transfer", return_value=""
    ), mock.patch.object(
        Manager, "before_execution"
    ), mock.patch.object(
        Manager, "create_job_in_db"
    ):

        def build_and_execute(**kwargs):
            captured.clear()
            base = dict(
                docker_img="img",
                cmd="ls",
                env_vars={},
                workflow_uuid="uuid",
                workflow_workspace="/data",
                job_name="job",
                htcondor_max_runtime="3600",
            )
            base.update(kwargs)
            manager = Manager(**base)
            manager.execute()
            return captured["submit"]

        yield build_and_execute


# --- constructor wiring -------------------------------------------------------


def test_constructor_stores_htcondor_request_attributes(manager_dependencies):
    """Constructor must store the four new HTCondor request attributes."""
    manager = htcondorcern_job_manager.HTCondorJobManagerCERN(
        docker_img="img",
        cmd="ls",
        env_vars={},
        workflow_uuid="uuid",
        workflow_workspace="/data",
        job_name="job",
        htcondor_request_cpus="4",
        htcondor_request_memory="4000",
        htcondor_request_disk="100000",
        htcondor_requirements='(Arch =?= "aarch64")',
    )
    assert manager.htcondor_request_cpus == "4"
    assert manager.htcondor_request_memory == "4000"
    assert manager.htcondor_request_disk == "100000"
    assert manager.htcondor_requirements == '(Arch =?= "aarch64")'


def test_constructor_defaults_htcondor_request_attributes_to_empty(
    manager_dependencies,
):
    """When unset, the four new HTCondor request attributes default to empty."""
    manager = htcondorcern_job_manager.HTCondorJobManagerCERN(
        docker_img="img",
        cmd="ls",
        env_vars={},
        workflow_uuid="uuid",
        workflow_workspace="/data",
        job_name="job",
    )
    assert manager.htcondor_request_cpus == ""
    assert manager.htcondor_request_memory == ""
    assert manager.htcondor_request_disk == ""
    assert manager.htcondor_requirements == ""


def test_constructor_scopes_kerberos_secrets_for_backend_auth(manager_dependencies):
    """HTCondor auth should preserve Kerberos secrets even with ``secret_names: []``."""
    all_user_secrets = UserSecrets(
        user_id="123",
        k8s_secret_name="k8s-secret",
        secrets=[
            Secret("ordinary", "env", "1"),
            Secret("CERN_USER", "env", "johndoe"),
            Secret("CERN_KEYTAB", "env", ".keytab"),
            Secret(".keytab", "file", b"keytab"),
        ],
    )

    with mock.patch.object(
        htcondorcern_job_manager,
        "initialize_krb5_token",
    ) as initialize_krb5_token:
        htcondorcern_job_manager.HTCondorJobManagerCERN(
            docker_img="img",
            cmd="ls",
            env_vars={},
            workflow_uuid="uuid",
            workflow_workspace="/data",
            job_name="job",
            secret_names=[],
            secrets=all_user_secrets,
        )

    scoped_secrets = initialize_krb5_token.call_args.kwargs["secrets"]
    assert list(scoped_secrets.secrets) == ["CERN_USER", "CERN_KEYTAB", ".keytab"]


# --- submit-description mapping in execute() ----------------------------------


def test_execute_builds_v2_submit_description(captured_submit):
    """The manager must use the v2 Submit API with string values."""
    submit = captured_submit()

    assert isinstance(submit, htcondor.Submit)
    assert submit["description"] == "wf_job"
    assert submit["executable"] == "/data/job_wrapper.sh"
    assert submit["initialdir"].startswith("/data/reana_job.")
    assert submit["initialdir"].endswith(".filetransfer")
    assert submit["MY.JobMaxRetries"] == "3"
    assert submit["MY.DockerImage"] == classad.quote("img")
    assert submit["MY.WantDocker"] == "True"
    assert submit["MY.DockerNetworkType"] == classad.quote("host")
    assert submit["MY.MaxRunTime"] == "3600"
    assert submit["MY.Requirements"] == "True"
    assert "log" not in submit.keys()
    assert all(isinstance(value, str) for value in submit.values())


def test_execute_preserves_unpacked_image_submission(captured_submit):
    """Unpacked images must keep using the generated Singularity wrapper."""
    submit = captured_submit(unpacked_img=True)

    assert submit["executable"] == "/data/job_singularity_wrapper.sh"
    assert "arguments" not in submit.keys()
    assert "MY.DockerImage" not in submit.keys()
    assert "MY.WantDocker" not in submit.keys()


def test_execute_sets_request_cpus_as_string(captured_submit):
    submit = captured_submit(htcondor_request_cpus="4")
    assert submit["request_cpus"] == "4"


def test_execute_converts_request_memory_to_mib(captured_submit):
    submit = captured_submit(htcondor_request_memory="4 GB")
    assert submit["request_memory"] == "4096"


def test_execute_rounds_up_request_memory(captured_submit):
    """A ``1 KB`` request must not silently become ``0`` MiB."""
    submit = captured_submit(htcondor_request_memory="1 KB")
    assert submit["request_memory"] == "1"


def test_execute_converts_request_disk_to_kib(captured_submit):
    submit = captured_submit(htcondor_request_disk="10 GB")
    assert submit["request_disk"] == "10485760"


def test_execute_sets_requirements_as_complete_classad_expression(captured_submit):
    submit = captured_submit(htcondor_requirements='(Arch =?= "aarch64")')
    rendered = submit["MY.Requirements"]
    expr = classad.ExprTree(rendered)

    assert isinstance(expr, classad.ExprTree)
    # Asserting on stable fragments rather than exact normal form, since
    # classad2's str() can vary in spacing/case across library versions.
    assert "Arch" in rendered
    assert "=?=" in rendered
    assert "aarch64" in rendered


def test_execute_formats_multiple_environment_variables(captured_submit):
    """Environment variables must use HTCondor's portable new syntax."""
    submit = captured_submit(env_vars={"CACHE": "on", "LABEL": "two words"})
    environment = submit["environment"]

    assert environment.startswith("\"'CACHE=on' 'LABEL=two words' ")
    assert "'REANA_WORKSPACE=/data'" in environment
    assert "'REANA_WORKFLOW_UUID=uuid'" in environment
    assert environment.endswith('"')


def test_format_env_vars_escapes_quotes(manager):
    """Environment syntax must preserve literal single and double quotes."""
    manager.env_vars = {"QUOTED": "a'b\"c"}

    assert manager._format_env_vars() == "\"'QUOTED=a''b\"\"c'\""


@pytest.mark.parametrize("forbidden_character", ["\n", "\r", "\x00"])
def test_execute_rejects_submit_command_injection(captured_submit, forbidden_character):
    """Untrusted values must not create additional submit-file lines."""
    job_name = "job{}MY.MaxRunTime = 999999".format(forbidden_character)

    with pytest.raises(ValueError, match="description"):
        captured_submit(job_name=job_name)


def test_execute_rejects_environment_command_injection(captured_submit):
    """Environment values must not inject additional submit-file lines."""
    env_vars = {"CACHE": "on\nMY.MaxRunTime = 999999"}

    with pytest.raises(ValueError, match="environment"):
        captured_submit(env_vars=env_vars)


def test_execute_omits_optional_request_attrs_when_absent(captured_submit):
    """Absent resource requests must not appear in the submit description."""
    submit = captured_submit()
    keys = submit.keys()

    assert "request_cpus" not in keys
    assert "request_memory" not in keys
    assert "request_disk" not in keys
    assert submit["MY.Requirements"] == "True"


# --- output staging ----------------------------------------------------------


@pytest.fixture
def workspace_manager(manager_dependencies, tmp_path):
    """Construct an HTCondor manager with a temporary workflow workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = htcondorcern_job_manager.HTCondorJobManagerCERN(
        docker_img="img",
        cmd="ls",
        env_vars={},
        workflow_uuid="uuid",
        workflow_workspace=str(workspace),
        job_name="job",
    )
    return manager


def test_prepare_file_transfer_uses_job_uuid_workspace(workspace_manager):
    """Stage returned files under the workflow workspace using the job UUID."""
    workspace = workspace_manager.workflow_workspace
    input_path = os.path.join(workspace, "input.txt")
    with open(input_path, "w") as input_file:
        input_file.write("input")

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"), mock.patch.object(
        workspace_manager, "_hash_file"
    ) as hash_file:
        input_files = workspace_manager._prepare_file_transfer()

    assert input_files == input_path
    assert workspace_manager.job_id in workspace_manager.file_transfer_workspace
    assert os.path.isdir(workspace_manager.file_transfer_workspace)
    assert workspace_manager.input_file_signatures["input.txt"]
    hash_file.assert_not_called()


def test_prepare_file_transfer_records_symlinks_without_following_them(
    workspace_manager,
):
    """Do not inspect symlink targets when snapshotting the workspace."""
    workspace = workspace_manager.workflow_workspace
    dangling_link = os.path.join(workspace, "dangling-link")
    os.symlink("missing-target", dangling_link)

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"), mock.patch.object(
        workspace_manager, "_hash_file"
    ) as hash_file:
        workspace_manager._prepare_file_transfer()

    assert "dangling-link" in workspace_manager.input_symlinks
    assert "dangling-link" not in workspace_manager.input_file_signatures
    hash_file.assert_not_called()


def test_get_input_files_excludes_file_transfer_directories(workspace_manager):
    """Do not send another HTCondor job's staging directory as input."""
    transfer_directory = os.path.join(
        workspace_manager.workflow_workspace,
        "reana_job.another-job.filetransfer",
    )
    os.makedirs(transfer_directory)

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        input_files = workspace_manager._get_input_files().split(",")

    assert "reana_job.another-job.filetransfer" not in input_files


def test_prepare_file_transfer_excludes_yadage_engine_state(workspace_manager):
    """Do not transfer or snapshot Yadage's concurrently updated state."""
    workspace_manager.workflow.type_ = "yadage"
    workspace = workspace_manager.workflow_workspace
    code_directory = os.path.join(workspace, "code")
    os.makedirs(code_directory)
    with open(os.path.join(code_directory, "analysis.py"), "w") as analysis:
        analysis.write("print('hello')")
    yadage_state = os.path.join(workspace, "_yadage", "adage")
    os.makedirs(yadage_state)
    with open(os.path.join(yadage_state, "adagesnap.txt"), "w") as snapshot:
        snapshot.write("engine state")

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        input_files = workspace_manager._prepare_file_transfer().split(",")

    assert input_files == [code_directory]
    assert not any(
        path == "_yadage" or path.startswith("_yadage/")
        for path in workspace_manager.input_file_signatures
    )


def test_prepare_file_transfer_excludes_snakemake_engine_state(workspace_manager):
    """Do not transfer or snapshot Snakemake's concurrently updated state."""
    workspace_manager.workflow.type_ = "snakemake"
    workspace = workspace_manager.workflow_workspace
    code_directory = os.path.join(workspace, "code")
    os.makedirs(code_directory)
    with open(os.path.join(code_directory, "analysis.py"), "w") as analysis:
        analysis.write("print('hello')")
    snakemake_state = os.path.join(workspace, ".snakemake", "metadata")
    os.makedirs(snakemake_state)
    with open(os.path.join(snakemake_state, "result"), "w") as metadata:
        metadata.write("engine state")

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        input_files = workspace_manager._prepare_file_transfer().split(",")

    assert input_files == [code_directory]
    assert not any(
        path == ".snakemake" or path.startswith(".snakemake/")
        for path in workspace_manager.input_file_signatures
    )


def test_promote_output_ignores_returned_yadage_engine_state(workspace_manager):
    """Do not overwrite Yadage state defensively if HTCondor returns it."""
    workspace_manager.workflow.type_ = "yadage"
    workspace = workspace_manager.workflow_workspace
    yadage_state = os.path.join(workspace, "_yadage", "adage")
    os.makedirs(yadage_state)
    snapshot_path = os.path.join(yadage_state, "adagesnap.txt")
    with open(snapshot_path, "w") as snapshot:
        snapshot.write("current engine state")

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    returned_yadage_state = os.path.join(
        workspace_manager.file_transfer_workspace, "_yadage", "adage"
    )
    os.makedirs(returned_yadage_state)
    with open(os.path.join(returned_yadage_state, "adagesnap.txt"), "w") as snapshot:
        snapshot.write("stale engine state")
    with open(
        os.path.join(workspace_manager.file_transfer_workspace, "result.txt"), "w"
    ) as result:
        result.write("result")

    workspace_manager.promote_output()

    with open(snapshot_path) as snapshot:
        assert snapshot.read() == "current engine state"
    with open(os.path.join(workspace, "result.txt")) as result:
        assert result.read() == "result"
    assert not os.path.exists(workspace_manager.file_transfer_workspace)


def test_promote_output_ignores_returned_snakemake_engine_state(workspace_manager):
    """Do not overwrite concurrently updated Snakemake state."""
    workspace_manager.workflow.type_ = "snakemake"
    workspace = workspace_manager.workflow_workspace
    snakemake_state = os.path.join(workspace, ".snakemake", "metadata")
    os.makedirs(snakemake_state)
    metadata_path = os.path.join(snakemake_state, "result")
    with open(metadata_path, "w") as metadata:
        metadata.write("initial engine state")

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    with open(metadata_path, "w") as metadata:
        metadata.write("current engine state")
    returned_snakemake_state = os.path.join(
        workspace_manager.file_transfer_workspace, ".snakemake", "metadata"
    )
    os.makedirs(returned_snakemake_state)
    with open(os.path.join(returned_snakemake_state, "result"), "w") as metadata:
        metadata.write("stale engine state")
    with open(
        os.path.join(workspace_manager.file_transfer_workspace, "result.txt"), "w"
    ) as result:
        result.write("result")

    workspace_manager.promote_output()

    with open(metadata_path) as metadata:
        assert metadata.read() == "current engine state"
    with open(os.path.join(workspace, "result.txt")) as result:
        assert result.read() == "result"
    assert not os.path.exists(workspace_manager.file_transfer_workspace)


def test_promote_output_moves_only_new_and_modified_files(workspace_manager):
    """Merge returned output without replacing unchanged input files."""
    workspace = workspace_manager.workflow_workspace
    input_path = os.path.join(workspace, "input.txt")
    modified_path = os.path.join(workspace, "modified.txt")
    with open(input_path, "w") as input_file:
        input_file.write("unchanged")
    input_inode = os.stat(input_path).st_ino
    with open(modified_path, "w") as modified_file:
        modified_file.write("before")

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    transfer_workspace = workspace_manager.file_transfer_workspace
    with open(os.path.join(transfer_workspace, "input.txt"), "w") as input_file:
        input_file.write("unchanged")
    with open(os.path.join(transfer_workspace, "modified.txt"), "w") as modified_file:
        modified_file.write("after")
    results = os.path.join(transfer_workspace, "results")
    os.makedirs(results)
    with open(os.path.join(results, "output.txt"), "w") as output_file:
        output_file.write("result")
    with open(os.path.join(transfer_workspace, "_condor_stdout"), "w") as stdout:
        stdout.write("duplicate standard output")
    with open(os.path.join(transfer_workspace, "_condor_stderr"), "w") as stderr:
        stderr.write("duplicate standard error")
    for filename in [
        ".chirp.config",
        ".job.ad",
        ".machine.ad",
        "condor_exec.exe",
    ]:
        with open(os.path.join(transfer_workspace, filename), "w") as internal_file:
            internal_file.write("HTCondor internal file")
    with open(os.path.join(transfer_workspace, "reana_job.123.0.out"), "w") as job_log:
        job_log.write("canonical job output")

    workspace_manager.promote_output()

    with open(input_path) as input_file:
        assert input_file.read() == "unchanged"
    assert os.stat(input_path).st_ino == input_inode
    with open(modified_path) as modified_file:
        assert modified_file.read() == "after"
    with open(os.path.join(workspace, "results", "output.txt")) as output_file:
        assert output_file.read() == "result"
    with open(os.path.join(workspace, "reana_job.123.0.out")) as job_log:
        assert job_log.read() == "canonical job output"
    assert not os.path.exists(os.path.join(workspace, "_condor_stdout"))
    assert not os.path.exists(os.path.join(workspace, "_condor_stderr"))
    for filename in workspace_manager.INTERNAL_OUTPUT_FILES:
        assert not os.path.exists(os.path.join(workspace, filename))
    assert not os.path.exists(transfer_workspace)


def test_promote_output_detects_same_size_change_with_preserved_mtime(
    workspace_manager,
):
    """Compare returned files lazily when transfer metadata is unchanged."""
    workspace = workspace_manager.workflow_workspace
    destination = os.path.join(workspace, "result.txt")
    with open(destination, "w") as result_file:
        result_file.write("before")
    original_mtime = os.stat(destination).st_mtime_ns

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    returned_file = os.path.join(
        workspace_manager.file_transfer_workspace, "result.txt"
    )
    with open(returned_file, "w") as result_file:
        result_file.write("after!")
    os.utime(returned_file, ns=(original_mtime, original_mtime))

    workspace_manager.promote_output()

    with open(destination) as result_file:
        assert result_file.read() == "after!"


def test_promote_output_preserves_input_symlink(workspace_manager):
    """Do not replace an input symlink with HTCondor's dereferenced copy."""
    workspace = workspace_manager.workflow_workspace
    target = os.path.join(workspace, "target.txt")
    input_link = os.path.join(workspace, "input-link")
    with open(target, "w") as target_file:
        target_file.write("input")
    os.symlink("target.txt", input_link)

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    with open(
        os.path.join(workspace_manager.file_transfer_workspace, "input-link"),
        "w",
    ) as returned_file:
        returned_file.write("input")

    workspace_manager.promote_output()

    assert os.path.islink(input_link)
    assert os.readlink(input_link) == "target.txt"
    with open(target) as target_file:
        assert target_file.read() == "input"


def test_promote_output_rejects_same_size_modified_input_symlink(workspace_manager):
    """Content-check same-size modifications through an input symlink."""
    workspace = workspace_manager.workflow_workspace
    target = os.path.join(workspace, "target.txt")
    input_link = os.path.join(workspace, "input-link")
    with open(target, "w") as target_file:
        target_file.write("input")
    os.symlink("target.txt", input_link)

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    returned_path = os.path.join(
        workspace_manager.file_transfer_workspace, "input-link"
    )
    with open(returned_path, "w") as returned_file:
        returned_file.write("other")

    assert os.path.getsize(returned_path) == os.path.getsize(target)
    with pytest.raises(RuntimeError, match="concurrently modified"):
        workspace_manager.promote_output()

    assert os.path.islink(input_link)
    with open(target) as target_file:
        assert target_file.read() == "input"
    assert os.path.isdir(workspace_manager.file_transfer_workspace)


def test_promote_output_rejects_input_symlink_with_missing_target(
    workspace_manager,
):
    """Fail clearly when an input symlink target disappears."""
    workspace = workspace_manager.workflow_workspace
    target = os.path.join(workspace, "target.txt")
    input_link = os.path.join(workspace, "input-link")
    with open(target, "w") as target_file:
        target_file.write("input")
    os.symlink("target.txt", input_link)

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    os.unlink(target)
    with open(
        os.path.join(workspace_manager.file_transfer_workspace, "input-link"),
        "w",
    ) as returned_file:
        returned_file.write("input")

    with pytest.raises(RuntimeError, match="concurrently modified"):
        workspace_manager.promote_output()

    assert os.path.islink(input_link)
    assert os.path.isdir(workspace_manager.file_transfer_workspace)


def test_promote_output_warns_when_skipping_input_directory_symlink(
    workspace_manager, caplog
):
    """Warn when discarding returned content beneath a directory symlink."""
    workspace = workspace_manager.workflow_workspace
    target = os.path.join(workspace, "target")
    input_link = os.path.join(workspace, "input-link")
    os.makedirs(target)
    with open(os.path.join(target, "input.txt"), "w") as input_file:
        input_file.write("input")
    os.symlink("target", input_link)

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    returned_directory = os.path.join(
        workspace_manager.file_transfer_workspace, "input-link"
    )
    os.makedirs(returned_directory)
    with open(os.path.join(returned_directory, "input.txt"), "w") as input_file:
        input_file.write("modified by job")

    with caplog.at_level(logging.WARNING):
        workspace_manager.promote_output()

    assert (
        "Skipping returned HTCondor content rooted at input directory symlink"
        in caplog.text
    )
    assert os.path.islink(input_link)
    with open(os.path.join(target, "input.txt")) as input_file:
        assert input_file.read() == "input"
    assert not os.path.exists(workspace_manager.file_transfer_workspace)


def test_promote_output_rejects_concurrent_modification(workspace_manager):
    """Do not overwrite a workspace file changed while the job was running."""
    workspace = workspace_manager.workflow_workspace
    destination = os.path.join(workspace, "result.txt")
    with open(destination, "w") as result_file:
        result_file.write("before")

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    with open(destination, "w") as result_file:
        result_file.write("local change")
    with open(
        os.path.join(workspace_manager.file_transfer_workspace, "result.txt"), "w"
    ) as result_file:
        result_file.write("remote change")

    with pytest.raises(RuntimeError, match="concurrently modified"):
        workspace_manager.promote_output()

    with open(destination) as result_file:
        assert result_file.read() == "local change"
    assert os.path.isdir(workspace_manager.file_transfer_workspace)


def test_promote_output_detects_replaced_file_with_preserved_metadata(
    workspace_manager,
):
    """Use inode metadata to notice same-size local file replacement."""
    workspace = workspace_manager.workflow_workspace
    destination = os.path.join(workspace, "result.txt")
    with open(destination, "w") as result_file:
        result_file.write("before")
    original_mtime = os.stat(destination).st_mtime_ns

    with mock.patch.object(workspace_manager, "_copy_wrapper_file"):
        workspace_manager._prepare_file_transfer()

    replacement = os.path.join(workspace, "replacement.txt")
    with open(replacement, "w") as result_file:
        result_file.write("local!")
    os.utime(replacement, ns=(original_mtime, original_mtime))
    os.replace(replacement, destination)

    returned_file = os.path.join(
        workspace_manager.file_transfer_workspace, "result.txt"
    )
    with open(returned_file, "w") as result_file:
        result_file.write("remote")
    os.utime(returned_file, ns=(original_mtime, original_mtime))

    with pytest.raises(RuntimeError, match="concurrently modified"):
        workspace_manager.promote_output()

    with open(destination) as result_file:
        assert result_file.read() == "local!"


# --- schedd interactions ------------------------------------------------------


def test_get_schedd_locates_configured_remote_schedd():
    """The v2 API must receive the remote schedd advertisement explicitly."""
    Manager = htcondorcern_job_manager.HTCondorJobManagerCERN
    schedd_host = "bigbird23.cern.ch"
    schedd_location = mock.sentinel.schedd_location
    schedd = mock.sentinel.schedd
    collector = mock.MagicMock()
    collector.locate.return_value = schedd_location
    mock_htcondor = mock.MagicMock()
    mock_htcondor.param = {"SCHEDD_HOST": schedd_host}
    mock_htcondor.Collector.return_value = collector
    mock_htcondor.Schedd.return_value = schedd

    with mock.patch.object(
        htcondorcern_job_manager, "htcondor", mock_htcondor
    ), mock.patch.object(
        htcondorcern_job_manager.thread_local,
        "MONITOR_THREAD_SCHEDD",
        None,
        create=True,
    ):
        assert Manager._get_schedd() is schedd
        assert Manager._get_schedd() is schedd

    collector.locate.assert_called_once_with(
        mock_htcondor.DaemonType.Schedd, schedd_host
    )
    mock_htcondor.Schedd.assert_called_once_with(schedd_location)


def test_get_schedd_does_not_fall_back_to_local_daemon():
    """A missing remote advertisement must not trigger local daemon lookup."""
    Manager = htcondorcern_job_manager.HTCondorJobManagerCERN
    collector = mock.MagicMock()
    collector.locate.return_value = None
    mock_htcondor = mock.MagicMock()
    mock_htcondor.param = {"SCHEDD_HOST": "missing.cern.ch"}
    mock_htcondor.Collector.return_value = collector

    with mock.patch.object(
        htcondorcern_job_manager, "htcondor", mock_htcondor
    ), mock.patch.object(
        htcondorcern_job_manager.thread_local,
        "MONITOR_THREAD_SCHEDD",
        None,
        create=True,
    ), pytest.raises(
        RuntimeError, match="missing.cern.ch"
    ):
        Manager._get_schedd.__wrapped__()

    mock_htcondor.Schedd.assert_not_called()


def test_submit_spools_submit_result_and_returns_cluster(manager):
    """A spooled v2 submission returns the cluster from SubmitResult."""
    submit = htcondor.Submit({"executable": "/bin/true"})
    result = mock.MagicMock()
    result.cluster.return_value = 123
    schedd = mock.MagicMock()
    schedd.submit.return_value = result
    Manager = htcondorcern_job_manager.HTCondorJobManagerCERN

    with mock.patch.object(
        Manager, "_get_schedd", return_value=schedd
    ), mock.patch.object(Manager, "_spool_input") as spool_input:
        assert manager._submit(submit) == 123

    schedd.submit.assert_called_once_with(submit, count=1, spool=True)
    spool_input.assert_called_once_with(result)


def test_spool_input_passes_submit_result_to_schedd():
    """The v2 spool API must receive the original SubmitResult."""
    result = mock.sentinel.submit_result
    schedd = mock.MagicMock()
    Manager = htcondorcern_job_manager.HTCondorJobManagerCERN

    with mock.patch.object(Manager, "_get_schedd", return_value=schedd):
        Manager._spool_input(result)

    schedd.spool.assert_called_once_with(result)


def test_stop_removes_job_and_its_spooled_files(manager):
    """Removing an HTCondor job must also release its remote spool data."""
    schedd = mock.MagicMock()
    Manager = htcondorcern_job_manager.HTCondorJobManagerCERN

    with mock.patch.object(Manager, "_get_schedd", return_value=schedd):
        manager.stop(123)

    schedd.act.assert_called_once_with(htcondor.JobAction.Remove, "ClusterId==123")


@pytest.mark.parametrize(
    "history, expected", [([], None), ([{"ClusterId": 123}], {"ClusterId": 123})]
)
def test_find_job_in_history_handles_v2_list_result(history, expected):
    """The v2 history API returns a list rather than an iterator."""
    schedd = mock.MagicMock()
    schedd.history.return_value = history
    Manager = htcondorcern_job_manager.HTCondorJobManagerCERN

    with mock.patch.object(Manager, "_get_schedd", return_value=schedd):
        assert Manager.find_job_in_history(123) == expected


def test_query_condor_jobs_uses_v2_query():
    """Job monitoring must use query(), because v2 removed xquery()."""
    expected_jobs = [{"ClusterId": 1}]
    schedd = mock.MagicMock()
    schedd.query.return_value = expected_jobs
    manager = mock.MagicMock()
    manager._get_schedd.return_value = schedd
    manager_factory = mock.MagicMock(return_value=manager)
    backend_job_ids = [1, 2]

    with mock.patch.dict(
        job_monitor.COMPUTE_BACKENDS, {"htcondorcern": manager_factory}
    ):
        assert job_monitor.query_condor_jobs(None, backend_job_ids) == expected_jobs

    schedd.query.assert_called_once_with(
        constraint=job_monitor.format_condor_job_que_query(backend_job_ids),
        projection=[
            "ClusterId",
            "JobStatus",
            "ExitCode",
            "ExitStatus",
            "HoldReasonCode",
        ],
    )
