# -*- coding: utf-8 -*-
#
# This file is part of REANA.
# Copyright (C) 2017, 2018 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Volume template generation."""

import json
from string import Template

from reana_job_controller.config import SHARED_VOLUME_PATH_ROOT


def get_k8s_cephfs_volume():
    """Return k8s CephFS volume template.

    :returns: k8s CephFS volume spec as a dictionary.
    """
    return {
        "name": "reana-shared-volume",
        "persistentVolumeClaim": {
            "claimName": "manila-cephfs-pvc"
        },
        "readOnly": "false"
    }


def get_k8s_cvmfs_volume(repository):
    """Render k8s CVMFS volume template.

    :param repository: CVMFS repository to be mounted.
    :returns: k8s CVMFS volume spec as a dictionary.
    """
    K8S_CVMFS_TEMPLATE = Template("""{
        "name": "$repository-cvmfs-volume",
        "persistentVolumeClaim": {
            "claimName": "csi-cvmfs-$repository-pvc"
        },
        "readOnly": "true"
    }""")
    return json.loads(K8S_CVMFS_TEMPLATE.substitute(repository=repository))


def get_k8s_hostpath_volume():
    """Render k8s HostPath volume template.

    :returns: k8s HostPath spec as a dictionary.
    """
    K8S_HOSTPATH_TEMPLATE = Template("""{
        "name": "reana-shared-volume",
        "hostPath": {
            "path": "$path"
        }
    }""")
    return json.loads(K8S_HOSTPATH_TEMPLATE.substitute(
        path=SHARED_VOLUME_PATH_ROOT))
