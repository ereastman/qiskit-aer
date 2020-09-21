# This code is part of Qiskit.
#
# (C) Copyright IBM 2018, 2019.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

# pylint: disable=invalid-name, bad-continuation

"""Manager for Qiskit Aer cluster-backed simulations."""
from dask.distributed import Client, LocalCluster
from ..backends.aerbackend import AerBackend
from qiskit.pulse import Schedule
from .clusterjobset import JobSet
#from qiskit.providers.aer.backends.aerbackend import AerBackend

class AerClusterManager:
    """Manager for Qiskit Aer cluster-backed simulations."""

    def __init__(self, cluster=None, **assemble_config) -> None:
        """ClusterManager Constructor."""
        self._cluster = cluster or LocalCluster()
        self._client = Client(self._cluster)
        self._assemble_config = assemble_config
        #self._backend = backend
        #self._backend_options = backend_options
        #self._noise_model = noise_model

        self._job_sets = []

    def run(self, experiments, backend, name=None, backend_options=None,
            noise_model=None, validate=False):
        if not isinstance(backend, AerBackend):
            raise ValueError(
                "AerClusterManager only supports AerBackends. "
                "{} is not an AerBackend.".format(backend))

        if (any(isinstance(exp, Schedule) for exp in experiments) and
                not backend.configuration().open_pulse):
            raise ValueError(
                'Pulse schedules found, but the backend does not support pulse schedules.')

        job_set = JobSet(experiments, backend, backend_options, noise_model, validate, name=name, **self._assemble_config)
        job_set.run(executor=self._client)
        self._job_sets.append(job_set)

        return job_set
