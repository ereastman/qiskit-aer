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

"""Job managed by the Job Manager."""

import warnings
import logging
import functools
from typing import List, Optional, Union

from qiskit.providers.aer.backends.aerbackend import AerBackend
from qiskit.qobj import QasmQobj, PulseQobj
from qiskit.result import Result
from qiskit.providers import JobStatus, JobError

logger = logging.getLogger(__name__)


class CJob:
    """Job managed by the Cluster Manager."""

    def __init__(self, qobj, backend, backend_options=None, noise_model=None, validate=False,
                 name=None):
        """ManagedJob constructor.

        Args:
            start_index: Starting index of the experiment set.
            experiments_count: Number of experiments.
            job: Job to be managed, or ``None`` if not already known.
        """
        self._qobj = qobj
        self._backend = backend
        self._backend_options = backend_options
        self._noise_model = noise_model
        self._validate = validate
        self._name = name

        self._future = None
        self._result = None
        # Properties that may be populated by the future.
        self.submit_error = None

    def submit(self, executor) -> None:
        """Submit the job.

        Args:
            qobj: Qobj to run.
            backend: Backend to execute the experiments on.
            executor: The thread pool used to submit the job.
            submit_lock: Lock used to synchronize job submission.
        """

        # Submit the job in its own future.
        logger.debug("Submitting job %s in future", self._name)
        self._future = executor.submit(self._backend._run_job, self._name, self._qobj,
                        self._backend_options, self._noise_model, self._validate)
        logger.debug("Job %s future obtained", self._name)

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
            if self._future is None:
                raise JobError("Job not submitted yet!. You have to .submit() first!")
            return func(self, *args, **kwargs)
        return _wrapper

    @requires_submit
    def result(self, timeout = None, raises=False):
        """Return the result of the job.

        Args:
           timeout: Number of seconds to wait for job.
           raises: if True and the job raised an exception
                   this will raise the same exception
        Returns:
            Job result or ``None`` if result could not be retrieved.

        Raises:
            IBMQJobTimeoutError: If the job does not return results before a
                specified timeout.
        """
        if self._result:
            return self._result
        result = None
        if self._future is not None:
            try:
                result = self._future.result(timeout=timeout)
            except JobError as err:
                warnings.warn(
                    "Unable to retrieve job result for job {}".format(self._name))
                if raises:
                    raise err
        self._result = result
        return result

    @requires_submit
    def status(self):
        """Query the future for it's status

        Returns:
            Current job status, or ``None`` if an error occurred.
        """
        if self._future.running():
            _status = JobStatus.RUNNING
        elif self._future.cancelled():
            _status = JobStatus.CANCELLED
        elif self._future.done():
            _status = JobStatus.DONE if self._future.exception() is None else JobStatus.ERROR
        else:
            # Note: There is an undocumented Future state: PENDING, that seems to show up when
            # the job is enqueued, waiting for someone to pick it up. We need to deal with this
            # state but there's no public API for it, so we are assuming that if the job is not
            # in any of the previous states, is PENDING, ergo INITIALIZING for us.
            _status = JobStatus.INITIALIZING
        return _status

    @requires_submit
    def cancel(self):
        """Attempt to cancel the Job.

        Returns:
            False if the call cannot be cancelled, True otherwise"""
        return self._future.cancel()

    def qobj(self):
        """Return the Qobj submitted for this job.

        Returns:
            Qobj: the Qobj submitted for this job.
        """ 
        return self._qobj

    def name(self):
        """Return this job's name.

        Returns:
            Name: str name of this job.
        """
        return self._name
