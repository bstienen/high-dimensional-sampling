from abc import ABC, abstractmethod
import os
import getpass
import pandas as pd
import yaml
import copy
import numpy as np

from .utils import get_time, get_datetime, create_unique_folder, benchmark_matrix_inverse, benchmark_sha_hashing
from .methods import Method
from .functions import TestFunction


class Experiment(ABC):
    """
    Base class for performing experiments on Methods with TestFunctions

    This class allows to test sampling methods implemented as a derived class
    from the methods.Method class by letting it work on a TestFunction derived
    class instance. It automatically takes care of logging (through a Logger
    instance) and sanity checks.

    Args:
        method: An instance of a Method derived class that needs to be tested
            in this experiment.
        path: Path to which the experiment should write its logs.
    """

    def __init__(self, method, path):
        if not isinstance(method, Method):
            raise Exception(
                """SamplingExperiments should be provided an instance of a
                class derived from the methods.Sampler class.""")
        self.path = path
        self.method = method
        self.logger = None

    def _perform_experiment(self, function, log_data=True):
        """
        Run the experiment.

        Calling this method will run the experiment on the provided function.
        It will continue to run as long as the method being tested in this
        experiment is not finished (checked through its is_finished method)
        or a specified number of sampled datapoints is reached (configured
        via the finish_line argument of this method).

        Args:
            function: Function to run the experiment with. This should be an
                instance of a class with the functions.TestFunction class as
                base class.
            log_data: Boolean indicating if the sampled data should be logged
                as well. It is set to True by default.
            finish_line: If the total sampled data set reaches or exceeds this
                size, the experiment is stopped. This is a hard stop, not a
                stopping condition that has to be met: if the method being
                tested indicates it is finished, the experiment will be
                stopped, regardless of the size of the sampled data set. The
                finish_line is set to 10,000 by default. If set to None, the
                experiment will continue to run until the method indicates
                it is finished.

        Raises:
            Exception: Provided function should have functions.TestFunction as
                base class.
        """
        print("Run experiment for '{}' on function '{}'...".format(
            type(self.method).__name__,
            type(function).__name__))
        # Test if function is a TestFunction instance
        if not isinstance(function, TestFunction):
            raise Exception(
                """Provided function should have functions.TestFunction as
                base class.""")
        # Setup logger
        self.logger = Logger(self.path, (type(function).__name__).lower())
        self.logger.log_experiment(self, function)
        self.logger.log_benchmarks()
        # Make function available both to the Experiment and the Method
        self.function = function
        self.method.function = self.function
        # Perform sampling as long as procedure is not finished
        is_finished = False
        n_sampled = 0
        while not is_finished:
            self.logger.method_calls += 1
            # Perform an method iteration and keep track of time elapsed
            t_start = get_time()
            x, y = self.method(self.function)
            dt = get_time() - t_start
            # Log method call
            n = len(x)
            n_sampled += n
            self.logger.log_method_calls(dt, n_sampled, n)
            # Log sampled data
            if log_data:
                self.logger.log_samples(x, y)
            # Log function calls and reset the counter
            self.logger.log_function_calls(self.function)
            self.function.reset()
            # Check if the experiment has to stop and update the while
            # condition to control this.
            is_finished = (self.method.is_finished()
                           or self._stop_experiment(x, y))
        # Delete the logger to close all handles
        del (self.logger)

    @abstractmethod
    def run(self):
        pass

    @abstractmethod
    def _stop_experiment(self, x, y):
        pass


class OptimisationExperiment(Experiment):
    """
    Class for performing optimisation experiments.

    This class allows for performing optimisation experiments implemented as a
    derived class from the methods.Method class by letting them work on a 
    TestFunction derived derived class instance. It automatically takes care of
    logging (through a Logger instance) and sanity checks.
    
    The OptimisationExperiment implements functionality to set stopping
    criterea relevant for such experiments. The configuration of these stopping
    criterea is done through the `epsilon`, `absolute_improvement`, `patience`
    and `finish_line` arguments of the .run() method.

    Args:
        method: An instance of a Method derived class that needs to be tested
            in this experiment.
        path: Path to which the experiment should write its logs.
    """

    def run(self,
            function,
            epsilon,
            absolute_improvement,
            patience=100,
            finish_line=1000,
            log_data=True):
        """
        Run the optimisation experiment on the provided test function.

        The experiment is stopped if the method did not show an `epsilon`
        improvement over `patience` samplings. If `absolute_improvement` is set
        to True, the epsilon is interpreted as an absolute improvement,
        otherwise it is interpreted as a relative improvement. The finish_line
        configures a hard cut-off: if the total number of sampled points
        reaches or exceeds this number, the experiment is stopped (regardless
        of any other stopping criterion).

        OptimisationExperiment uses the Experiment class as its base class and
        is identical to the OptimizationExperiment class.

        Args:
            function: Function to run the experiment with. This should be an
                instance of a class with the functions.TestFunction class as
                base class.
            epsilon: Required improvement on the sampled value. If this is not
                obtained, the experiment is stopped. See the
                `absolute_improvement` and `patience` arguments for finetuning
                of this argument and stopping criterion.
            absolute_improvement: Boolean indicating if the epsilon argument
                should be interpreted as a requirement on the absolute
                improvement (True) or on the relative improvement (False).
            patience: Number of samples that the method may violate the 
                epsilon improvement requirement before the experiment is
                stopped. It is set to 100 by default.
            finish_line: If the total sampled data set reaches or exceeds this
                size, the experiment is stopped. This is a hard stop, not a
                stopping condition that has to be met: if the method being
                tested indicates it is finished, the experiment will be
                stopped, regardless of the size of the sampled data set. The
                finish_line is set to 1,000 by default. If set to None, the
                experiment will continue to run until the method indicates
                it is finished.
            log_data: Boolean indicating if the sampled data should be logged
                as well. It is set to True by default.
        """
        self.epsilon = epsilon
        self.absolute_improvement = absolute_improvement
        self.patience = patience
        self.finish_line = finish_line
        self.n_sampled = None
        self.optimals = []
        self._perform_experiment(function, log_data)

    def _stop_experiment(self, x, y):
        """
        Uses the stopping criterion defined in the .run() method to determine
        if the experiment should be stopped.

        Args:
            x: Sampled data in the form of a numpy.ndarray of shape
                (nDatapoints, nVariables).
            y: Function values for the samples datapoints of shape
                (nDatapoints, ?)
        
        Returns:
            Boolean indicating if the experiment should be stopped (i.e. the
            stopping criterion is reached).
        """
        if self.n_sampled is None:
            self.n_sampled = [len(x)]
        else:
            self.n_sampled.append(self.n_sampled[-1] + len(x))
        if self.n_sampled[-1] > self.finish_line:
            return True
        self.optimals.append(np.min(y))
        if self._sampled_since_last_improvement() > self.patience:
            return True
        return False

    def _sampled_since_last_improvement(self):
        """
        Calculated the number of data points sampled since the last epsilon
        improvement. Both epsilon and the interpretation of epsilon (i.e.
        absolute_improvement) are taken from the .run() arguments

        Returns:
            Number of samples sampled since last epsilon improvement.
        """
        cut = self.optimals[-1]
        for i in range(len(self.optimals) - 2, 0, -1):
            if self.absolute_improvement:
                condition = cut - self.optimals[i]
            else:
                condition = self.optimals[i] / float(cut)
            if condition > self.epsilon:
                return self.n_sampled[-1] - self.n_sampled[i]
        return self.n_sampled[-1] - self.n_sampled[0]


class OptimizationExperiment(OptimisationExperiment):
    """
    Alias of the OptimisationExperiment class
    """
    pass


class PosteriorSamplingExperiment(Experiment):
    """
    Class for performing optimisation experiments.

    This class allows for performing posterior sampling methods implemented as
    a derived class from the methods.Method class by letting it work on a
    TestFunction derived class instance. It automatically takes care of
    logging (through a Logger instance) and sanity checks.

    Args:
        method: An instance of a Method derived class that needs to be tested
            in this experiment.
        path: Path to which the experiment should write its logs.
    """

    def run(self, function, finish_line=1000, log_data=True):
        """
        Run the posterior sampling experiment on the provided test function.

        The experiment is stopped if the total number of sampled points reaches
        or exceeds the number defined in the `finish_line` argument.

        Args:
            function: Function to run the experiment with. This should be an
                instance of a class with the functions.TestFunction class as
                base class.
            finish_line: If the total sampled data set reaches or exceeds this
                size, the experiment is stopped. This is a hard stop, not a
                stopping condition that has to be met: if the method being
                tested indicates it is finished, the experiment will be
                stopped, regardless of the size of the sampled data set. The
                finish_line is set to 10,000 by default. If set to None, the
                experiment will continue to run until the method indicates
                it is finished.
            log_data: Boolean indicating if the sampled data should be logged
                as well. It is set to True by default.
        """
        self.finish_line = finish_line
        self.n_sampled = 0
        self._perform_experiment(function, log_data)

    def _stop_experiment(self, x, y):
        """
        Uses the stopping criterion defined in the .run() method to determine
        if the experiment should be stopped.

        Args:
            x: Sampled data in the form of a numpy.ndarray of shape
                (nDatapoints, nVariables).
            y: Function values for the samples datapoints of shape
                (nDatapoints, ?)
        
        Returns:
            Boolean indicating if the experiment should be stopped (i.e. the
            stopping criterion is reached).
        """
        self.n_sampled += len(x)
        if self.n_sampled >= self.finish_line:
            return True
        return False


class Logger:
    """
    Class that takes care of all logging of experiments.

    An instance of this class is automatically made and handled within the
    Experiment class.

    Args:
        path: Path to which logging results should be written. Within this
            folder each test function will get its own subfolder.
        prefered_subfolder: Name of the folder to be created in the logging
            path. The folder is created with the utils.create_unique_folder
            function, so naming conflicts will be automatically resolved.
    """

    def __init__(self, path, prefered_subfolder):
        self.basepath = path
        self.path = create_unique_folder(path, prefered_subfolder)
        self.method_calls = 0
        self.create_samples_header = True
        self._create_handles()

    def __del__(self):
        """
        Closes all the opened handles at deletion of the instance.
        """
        handles = ["samples", "functioncalls", "methodcalls"]
        for handle in handles:
            if hasattr(self, 'handle_' + handle):
                getattr(self, 'handle_' + handle).close()

    def _create_handles(self):
        """
        Creates the file handles needed for logging. Created csv files also get
        their headers added if already possible.
        """
        self.handle_samples = open(self.path + os.sep + "samples.csv", "w")
        self.handle_functioncalls = open(
            self.path + os.sep + "functioncalls.csv", "w")
        self.handle_functioncalls.write(
            'method_call_id,n_queried,dt,asked_for_derivative\n')
        self.handle_methodcalls = open(self.path + os.sep + "methodcalls.csv",
                                       "w")
        self.handle_methodcalls.write(
            'method_call_id,dt,total_dataset_size,new_data_generated\n')

    def log_samples(self, x, y):
        """
        Log samples and their obtained function values from the test function.

        The data and their target values are written to the samples.csv file
        created at initialisation of the Logger object. As this is the first
        moment we know how many parameters the problem has, this function will
        create a header in this file as well if it is called for the first
        time.

        Args:
            x: numpy.ndarray of shape (nDatapoints, nVariables) containing the
                data to be logged.
            y: numpy.ndarray of shape (nDatapoints, nTargetVariables)
                containing the sampled function values of the test function.
        """
        # Create header
        if self.create_samples_header:
            header = ['method_call_id']
            header += ['x' + str(i) for i in range(len(x[0]))]
            header += ['y' + str(i) for i in range(len(y[0]))]
            self.handle_samples.write(",".join(header) + "\n")
            self.create_samples_header = False
        # Create and write line
        n_datapoints = len(x)
        points = x.astype(str).tolist()
        labels = y.astype(str).tolist()
        for i in range(n_datapoints):
            line = [str(self.method_calls)]
            line += points[i]
            line += labels[i]
            self.handle_samples.write(','.join(line) + "\n")
        self.handle_samples.flush()

    def log_method_calls(self, dt, size_total, size_generated):
        """
        Log a method call to the methodscalls.csv file.

        Args:
            dt: Time in ms spend on the method call.
            size_total: Number of data points sampled in total for all
                method calls so far. This should include the data points
                sampled in the iteration that is currently sampled.
            size_generated: Number of data points sampled in this specific
                method call.
        """
        line = [
            int(self.method_calls), dt,
            int(size_total),
            int(size_generated)
        ]
        line = list(map(str, line))
        self.handle_methodcalls.write(','.join(line) + "\n")

    def log_function_calls(self, function):
        """
        Log the number of calls to the test function and whether or not it is
        queried for a derivative.

        Function calls will be logged in the functioncalls.csv file.

        Args:
            function: Test function that was used in an experiment iteration.
                This test function should be a class with
                functions.TestFunction as its base class.
        """
        for entry in function.counter:
            line = [
                int(self.method_calls),
                int(entry[0]),
                float(entry[1]),
                bool(entry[2])
            ]
            line = list(map(str, line))
            self.handle_functioncalls.write(','.join(line) + "\n")

    def log_benchmarks(self):
        """
        Benchmark the machine with some simple benchmark algorithms (as
        implemented in the utils module).

        Results are stored in the base log path in the benchmarks.yaml file. If
        this file already exists, no benchmarks are run.
        """
        if os.path.exists(self.basepath + os.sep + "benchmarks.yaml"):
            return
        with open(self.basepath + os.sep + "benchmarks.yaml", "w") as handle:
            info = {}
            # Get meta data of experiment
            info['benchmarks'] = {
                'matrix_inversion': benchmark_matrix_inverse(),
                'sha_hashing': benchmark_sha_hashing(),
            }
            yaml.dump(info, handle, default_flow_style=False)

    def log_experiment(self, experiment, function):
        """
        Log the setup and the function set up to a .yaml-file in order to
        optimize reproducability.

        This method should be called *before* the first experiment iteration.

        Args:
            experiment: Experiment to be run, containing the method to be
                tested (which needs to be provided at initialisation).
            function: Test function that was used in an experiment iteration.
                This test function should be a class with
                functions.TestFunction as its base class.
        """
        with open(self.path + os.sep + "experiment.yaml", "w") as handle:
            info = {}
            # Get meta data of experiment
            info['meta'] = {
                'datetime': str(get_datetime()),
                'timestamp': str(get_time()),
                'user': getpass.getuser(),
            }
            # Get properties of function
            info['function'] = {
                'name': type(function).__name__,
                'properties': copy.copy(vars(function))
            }
            del (info['function']['properties']['counter'])
            # Get properties of experiment
            info['method'] = {
                'name': type(experiment.method).__name__,
                'properties': {}
            }
            for prop in experiment.method.store_parameters:
                info['method']['properties'][prop] = getattr(
                    experiment.method, prop)
            # Convert information to yaml and write to file
            yaml.dump(info, handle, default_flow_style=False)
