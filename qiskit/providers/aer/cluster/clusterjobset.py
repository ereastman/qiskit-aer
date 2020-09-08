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

from qiskit.circuit import QuantumCircuit
from qiskit.pulse import Schedule
from qiskit.compiler import assemble
from qiskit.qobj import QasmQobj, PulseQobj
from qiskit.providers import JobError
from qiskit.providers.jobstatus import JobStatus

from .clusterjob import ClusterJob
from .clusterresults import ClusterResults
from ..aerjob import requires_submit


logger = logging.getLogger(__name__)


class ClusterJobSet:
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

    def __init__(
            self,
            name: Optional[str] = None,
            short_id: Optional[str] = None
    ) -> None:
        """ClusterJobSet constructor.

        Args:
            name: Name for this set of jobs. If not specified, the current
                date and time is used.
            short_id: Short ID for this set of jobs.
        """
        self._managed_jobs = []  # type: List[ManagedJob]
        self._name = name or datetime.utcnow().isoformat()
        self._backend = None  # type: Optional[IBMQBackend]
        self._id = short_id or uuid.uuid4().hex + '-' + str(time.time()).replace('.', '')
        self._id_long = self._id_prefix + self._id + self._id_suffix
        self._job_submit_lock = threading.Lock()  # Used to synchronize job submit.

        # Used for caching
        self._managed_results = None  # type: Optional[ManagedResults]
        self._error_msg = None  # type: Optional[str]

    def run(
            self,
            experiment_list: Union[List[List[QuantumCircuit]], List[List[Schedule]]],
            backend: AerBackend,
            executor: ThreadPoolExecutor,
            **assemble_config: Any
    ) -> None:
        """Execute a list of circuits or pulse schedules on a backend.

        Args:
            experiment_list : Circuit(s) or pulse schedule(s) to execute.
            backend: Backend to execute the experiments on.
            executor: The thread pool used to submit jobs asynchronously.
            job_share_level: Job share level.
            job_tags: Tags to be assigned to the job.
            assemble_config: Additional arguments used to configure the Qobj
                assembly. Refer to the :func:`qiskit.compiler.assemble` documentation
                for details on these arguments.

        Raises:
            IBMQJobManagerInvalidStateError: If the jobs were already submitted.
        """
        if self._managed_jobs:
            raise IBMQJobManagerInvalidStateError(
                'The jobs for this managed job set have already been submitted.')

        self._backend = backend

        exp_index = 0
        total_jobs = len(experiment_list)
        for i, experiments in enumerate(experiment_list):
            qobj = assemble(experiments, backend=backend, **assemble_config)
            job_name = JOB_SET_NAME_FORMATTER.format(self._name, i)
            cjob = ClusterJob(experiments_count=len(experiments), start_index=exp_index)
            logger.debug("Submitting job %s/%s for job set %s", i+1, total_jobs, self._name)
            cjob.submit(qobj=qobj, job_name=job_name, backend=backend,
                        executor=executor, job_share_level=job_share_level,
                        job_tags=self._tags+[self._id_long], submit_lock=self._job_submit_lock)
            logger.debug("Job %s submitted", i+1)
            self._managed_jobs.append(mjob)
            exp_index += len(experiments)
 
    def statuses(self) -> List[Union[JobStatus, None]]:
        """Return the status of each job in this set.

        Returns:
            A list of job statuses. An entry in the list is ``None`` if the
            job status could not be retrieved due to a server error.
        """
        return [mjob.status() for mjob in self._managed_jobs]

    @requires_submit
    def results(
            self,
            timeout: Optional[float] = None,
    ) -> ClusterResults:
        """Return the results of the jobs.

        This call will block until all job results become available or
        the timeout is reached.

        Note:
            When `partial=True`, this method will attempt to retrieve partial
            results of failed jobs. In this case, precaution should
            be taken when accessing individual experiments, as doing so might
            cause an exception. The ``success`` attribute of the returned
            :class:`ManagedResults`
            instance can be used to verify whether it contains
            partial results.

            For example, if one of the experiments failed, trying to get the counts
            of the unsuccessful experiment would raise an exception since there
            are no counts to return::

                try:
                    counts = managed_results.get_counts("failed_experiment")
                except QiskitError:
                    print("Experiment failed!")

        Args:
           timeout: Number of seconds to wait for job results.
           partial: If ``True``, attempt to retrieve partial job results.
           refresh: If ``True``, re-query the server for the result. Otherwise
                return the cached value.

        Returns:
            A :class:`ManagedResults`
            instance that can be used to retrieve results
            for individual experiments.

        Raises:
            IBMQJobManagerTimeoutError: if unable to retrieve all job results before the
                specified timeout.
        """
        if self._managed_results is not None and not refresh:
            return self._managed_results

        start_time = time.time()
        original_timeout = timeout
        success = True

        # TODO We can potentially make this multithreaded
        for mjob in self._managed_jobs:
            try:
                result = mjob.result(timeout=timeout, partial=partial, refresh=refresh)
                if result is None or not result.success:
                    success = False
            except IBMQJobTimeoutError as ex:
                raise IBMQJobManagerTimeoutError(
                    'Timeout while waiting for the results for experiments {}-{}.'.format(
                        mjob.start_index, self._managed_jobs[-1].end_index)) from ex

            if timeout:
                timeout = original_timeout - (time.time() - start_time)
                if timeout <= 0:
                    raise IBMQJobManagerTimeoutError(
                        'Timeout while waiting for the results for experiments {}-{}.'.format(
                            mjob.start_index, self._managed_jobs[-1].end_index))

        self._managed_results = ManagedResults(self, self._backend.name(), success)

        return self._managed_results

    @requires_submit
    def cancel(self) -> None:
        """Cancel all jobs in this job set."""
        for mjob in self._managed_jobs:
            mjob.cancel()

    @requires_submit
    def jobs(self) -> List[Union[IBMQJob, None]]:
        """Return jobs in this job set.

        Returns:
            A list of :class:`~qiskit.providers.ibmq.job.IBMQJob`
            instances that represents the submitted jobs.
            An entry in the list is ``None`` if the job failed to be submitted.
        """
        return [mjob.job for mjob in self._managed_jobs]

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

    def managed_jobs(self) -> List[ClusterJob]:
        """Return the managed jobs in this set.

        Returns:
            A list of managed jobs.
        """
        return self._managed_jobs
