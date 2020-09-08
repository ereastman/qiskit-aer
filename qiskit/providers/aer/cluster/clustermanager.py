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
from .aerbackend import AerBackend

class AerClusterManager:
    """Manager for Qiskit Aer cluster-backed simulations."""

    def __init__(self, cluster=None) -> None:
        """ClusterManager Constructor."""
        self._job_sets = [] # type: List[ManagedJobSet]
        self._cluster = cluster or LocalCluster()
        self._client = Client(cluster)

    def run(self,
            experiments: Union[List[QuantumCircuit], List[Schedule]],
            backend: AerBackend,
            name: Optional[str] = None,
            max_experiments_per_job: Optional[int] = None,
            **run_config: Any
    ) -> ManagedJobSet:
        if (any(isinstance(exp, Schedule) for exp in experiments) and
                not backend.configuration().open_pulse):
            raise ValueError(
                'Pulse schedules found, but the backend does not support pulse schedules.')

        if not isinstance(backend, AerBackend):
            raise ValueError(
                "AerClusterManager only supports AerBackends. "
                "{} is not an AerBackend.".format(backend))

        job_set = ClusterJobSet(name=name)
        job_set.run(experiments, backend=backend, executor=self._client, **run_config)
        self._job_sets.append(job_set)

        return job_set
