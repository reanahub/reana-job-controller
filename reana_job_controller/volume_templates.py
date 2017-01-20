import json
from string import Template

CEPH_SECRET_NAME = 'ceph-secret'

CEPHFS_PATHS = {
    'alice': '/k8s/alice',
    'atlas': '/k8s/atlas',
    'cms': '/k8s/cms',
    'lhcb': '/k8s/lhcb',
    'recast': '/k8s/recast'
}

CVMFS_REPOSITORIES = {
    'alice': 'alice.cern.ch',
    'alice-ocdb': 'alice-ocdb.cern.ch',
    'atlas': 'atlas.cern.ch',
    'atlas-condb': 'atlas-condb.cern.ch',
    'cms': 'cms.cern.ch',
    'lhcb': 'lhcb.cern.ch',
    'na61': 'na61.cern.ch',
    'boss': 'boss.cern.ch',
    'grid': 'grid.cern.ch',
    'sft': 'sft.cern.ch',
    'geant4': 'geant4.cern.ch'
}

CEPHFS_MOUNT_PATH = '/data'

k8s_cephfs_template = Template("""{
    "name": "cephfs-$experiment",
    "cephfs": {
        "monitors": [
            "128.142.36.227:6790",
            "128.142.39.77:6790",
            "128.142.39.144:6790"
        ],
        "path": "$path",
        "user": "k8s",
        "secretRef": {
            "name": "$secret_name",
            "readOnly": false
        }
    }
}""")

k8s_cvmfs_template = Template("""{
    "name": "cvmfs-$experiment",
    "flexVolume": {
        "driver": "cern/cvmfs",
        "options": {
            "repository": "$repository"
        }
    }
}""")


def get_cvmfs_mount_point(repository_name):
    return '/cvmfs/{repository}'.format(
        repository=CVMFS_REPOSITORIES[repository_name]
    )


def get_k8s_cephfs_volume(experiment):
    """Render k8s CephFS volume template

    :param experiment: Experiment name.
    :returns: k8s CephFS volume spec as a dictionary.
    """
    return json.loads(
        k8s_cephfs_template.substitute(experiment=experiment,
                                       path=CEPHFS_PATHS[experiment],
                                       secret_name=CEPH_SECRET_NAME)
    )


def get_k8s_cvmfs_volume(experiment, repository):
    """Render k8s CVMFS volume template

    :param experiment: Experiment name.
    :returns: k8s CVMFS volume spec as a dictionary.
    """
    if repository in CVMFS_REPOSITORIES:
        return json.loads(k8s_cvmfs_template.substitute(experiment=experiment,
                                                        repository=repository))
    else:
        raise ValueError('The provided repository doesn\'t exist')
