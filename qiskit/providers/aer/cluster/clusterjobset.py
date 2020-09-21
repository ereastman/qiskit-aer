# -*- coding: utf-8 -*-

# This code is part of Qiskit.
#
# (C) Copyright IBM 2019, 2020.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""A set of jobs being managed by the :class:`IBMQJobManager`."""

from datetime import datetime
from typing import List, Optional, Union, Any, Tuple
from concurrent.futures import ThreadPoolExecutor
import time
import logging
import uuid
import threading
import functools

from qiskit.circuit import QuantumCircuit
from qiskit.pulse import Schedule
from qiskit.compiler import assemble
from qiskit.qobj import QasmQobj, PulseQobj
from qiskit.providers import JobError
from qiskit.providers.jobstatus import JobStatus

from .clusterjob import CJob
from .clusterresults import CResults

logger = logging.getLogger(__name__)

class JobSet:
    """A set of cluster jobs.

    An instance of this class is returned when you submit experiments using
    :meth:`AerClusterManager.run()`.
    It provides methods that allow you to interact
    with the jobs as a single entity. For example, you can retrieve the results
    for all of the jobs using :meth:`results()` and cancel all jobs using
    :meth:`cancel()`.
    """

    _id_prefix = "cluster_jobset_"
    _id_suffix = "_"

    def __init__(self, experiments, backend, backend_options=None, noise_model=None, validate=False,
                 name=None, **assemble_config) -> None:
        """JobSet constructor.

        Args:
            name: Name for this set of jobs. If not specified, the current
                date and time is used.
            short_id: Short ID for this set of jobs.
        """
        self._name = name or str(uuid.uuid4())
        self._experiments = experiments
        self._backend = backend  # type: Optional[IBMQBackend]
        self._backend_options = backend_options
        self._noise_model = noise_model
        self._validate = validate
        self._assemble_config = assemble_config

        # Used for caching
        self._futures = []
        self._cluster_results = None
        self._error_msg = None

    def requires_submit(func):
        """
        Decorator to ensure that a submit has been performed before
        calling the method.
 
        Args:
            func (callable): test function to be decorated.
 
        Returns:
            callable: the decorated function.
        """
        @functools.wraps(func)
        def _wrapper(self, *args, **kwargs):
            if not self._futures:
                raise JobError("JobSet not submitted yet!. You have to .run() first!")
            return func(self, *args, **kwargs)
        return _wrapper

    def run(self, executor) -> None:
        """Execute this set of jobs on an executor.

        Args:
            executor: The thread pool used to submit jobs asynchronously.

        Raises:
            RuntimeError: If the jobs were already submitted.
        """
        if self._futures:
            raise RuntimeError(
                'The jobs for this managed job set have already been submitted.')

        total_jobs = len(self._experiments)
        for i, exp in enumerate(self._experiments):
            qobj = assemble(exp, backend=self._backend, **self._assemble_config)
            job_name = f'{self._name}_{i}'
            cjob = CJob(qobj=qobj, backend=self._backend, backend_options=self._backend_options,
                        noise_model=self._noise_model, validate=self._validate, name=job_name)
            cjob.submit(executor=executor)
            logger.debug("Job %s submitted", i+1)
            self._futures.append(cjob)

    @requires_submit
    def statuses(self) -> List[Union[JobStatus, None]]:
        """Return the status of each job in this set.

        Returns:
            A list of job statuses. An entry in the list is ``None`` if the
            job status could not be retrieved due to a server error.
        """
        return [cjob.status() for cjob in self._futures]

    @requires_submit
    def results(
            self,
            timeout: Optional[float] = None,
            raises: Optional[bool] = False
    ) -> CResults:
        """Return the results of the jobs.

        This call will block until all job results become available or
        the timeout is reached. Analogous to dask.client.gather()
 
        Args:
           timeout: Number of seconds to wait for job results.

        Returns:
            A :class:`CResults`
            instance that can be used to retrieve results
            for individual experiments.

        Raises:
            IBMQJobManagerTimeoutError: if unable to retrieve all job results before the
                specified timeout.
        """
        if self._cluster_results is not None:
            return self._cluster_results

        start_time = time.time()
        original_timeout = timeout
        success = True

        # TODO We can potentially make this multithreaded
        for cjob in self._futures:
            try:
                result = cjob.result(timeout=timeout, raises=raises)
                if result is None or not result.success:
                    success = False
            except AerClusterTimeoutError as ex:
                raise AerClusterTimeoutError(
                    'Timeout while waiting for the results of experiment {}'.format(
                        cjob.name())) from ex

            if timeout:
                timeout = original_timeout - (time.time() - start_time)
                if timeout <= 0:
                    raise AerClusterTimeOutError(
                        "Timeout while waiting for JobSet results")

        self._cluster_results = CResults(self, self._backend.name(), success)

        return self._cluster_results

    @requires_submit
    def cancel(self) -> None:
        """Cancel all jobs in this job set."""
        for cjob in self._futures:
            cjob.cancel()

    @requires_submit
    def job(self, experiment):
        """Retrieve the job used to submit the specified experiment and its index.

        Args:
            experiment: Retrieve the job used to submit this experiment. Several
                types are accepted for convenience:

                    * str: The name of the experiment.
                    * QuantumCircuit: The name of the circuit instance will be used.
                    * Schedule: The name of the schedule instance will be used.

        Returns:
            A tuple of the job used to submit the experiment and the experiment index.

        Raises:
            AerClusterJobNotFound: If the job for the experiment could not
                be found.
        """
        if isinstance(experiment, (QuantumCircuit, Schedule)):
            experiment = experiment.name
        for job in self.jobs():
            for i, exp in enumerate(job.qobj().experiments):
                if hasattr(exp.header, 'name') and exp.header.name == experiment:
                    return job, i

        raise AerClusterJobNotFound(
            'Unable to find the job for experiment {}.'.format(experiment))

    @requires_submit
    def jobs(self) -> List[Union[CJob, None]]:
        """Return jobs in this job set.

        Returns:
            A list of :class:`~qiskit.providers.aer.cluster.CJob`
            instances that represents the submitted jobs.
            An entry in the list is ``None`` if the job failed to be submitted.
        """
        return self._futures

    def name(self) -> str:
        """Return the name of this job set.

        Returns:
            Name of this job set.
        """
        return self._name

    def job_set_id(self) -> str:
        """Return the ID of this job set.

        Returns:
            ID of this job set.
        """
        # Return only the short version of the ID to reduce the possibility the
        # full ID is used for another job.
        return self._id

    def managed_jobs(self) -> List[CJob]:
        """Return the managed jobs in this set.

        Returns:
            A list of managed jobs.
        """
        return self._futures
