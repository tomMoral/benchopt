import re
import time
import tempfile
import subprocess
from collections import namedtuple
from abc import ABC, abstractmethod

from .util import check_cmd_solver
from .util import pip_install_in_env
from .util import bash_install_in_env
from .util import pip_uninstall_in_env
from .util import check_import_solver
from .class_property import classproperty


# Possible sampling strategies
SAMPLING_STRATEGIES = ['iteration', 'tolerance']

# Named-tuple for the cost function
Cost = namedtuple('Cost', 'data scale objective solver sample time obj '
                          'idx_rep'.split(' '))


class ParametrizedNameMixin():
    parameters = {}

    def __init__(self, **parameters):
        self.parameters = parameters
        if not hasattr(self, 'parameter_template'):
            self.parameter_template = ",".join(
                [f"{k}={v}" for k, v in parameters.items()])

    @property
    @abstractmethod
    def name(self):
        """Each object should expose its name for plotting purposes."""
        ...

    @property
    def _name(self):
        """Hook to define a different template to format the parameters"""
        return f"{self.name}({self.parameter_template})"

    def __repr__(self):
        if len(self.parameters) == 0:
            return self.name.capitalize()
        return self._name.format(**self.parameters).capitalize()


class BaseSolver(ParametrizedNameMixin, ABC):

    # TODO: sampling strategy with eps/tol instead for solvers that do not
    #       expose the max number of iterations
    sampling_strategy = 'iteration'

    # Information on how to install the solver. The value of install_cmd should
    # be in {None, 'pip', 'bash'}. The API reads:
    #
    # - 'pip': The solver should have at least attribute `package_name`.
    #          BenchOpt will pip install `$package_name` and check it is
    #          possible to import `$package_name` in the virtualenv. It is also
    #          possible to give a different name for the install by defining a
    #          class attribute `package_install` and for the import with the
    #          class attribute `package_import`.
    #
    # - 'bash': The solver should have attribute `install_script` and
    #           `cmd_name`. BenchOpt will run `install_script` in a bash and
    #           provide the virtualenv's directory as an argument. It will also
    #           check that `cmd_name` is in the virtual_env PATH.
    install_cmd = None

    def __init__(self, **parameters):
        """Instantiate a solver with the given parameters and store them.

        All parameters `PARAM` that are passed through init will be accessible
        as `self.PARAM` in the class.
        """
        super().__init__(**parameters)
        for k, v in parameters.items():
            setattr(self, k, v)

    def _set_objective(self, **objective_parameters):
        """Store the objective_parameters to make sure this solver is picklable
        """
        self.objective_parameters = objective_parameters
        self.set_objective(**objective_parameters)

    # @staticmethod
    # def reconstruct(klass, parameters, objective_parameters):
    #     obj = klass(**parameters)
    #     obj.set_objective(**objective_parameters)
    #     return obj

    # def __reduce__(self):
    #     return self.reconstruct, (self.__class__, self.parameters,
    #                               self.objective_parameters)

    @abstractmethod
    def set_objective(self, **objective_parameters):
        """Prepare the objective for the solver."""
        ...

    @abstractmethod
    def run(self, n_iter):
        """Call the solver for n_iter iterations.

        This function should not return the parameters which will be
        retrieved by a subsequent call to get_result.

        Parameters
        ----------
        n_iter : int
            Number of iteration to run the solver for. It allows to sample the
            time/accuracy curve in the benchmark.
        """
        ...

    @abstractmethod
    def get_result(self):
        """Return the parameters computed by the previous run.

        The parameters should be returned as a flattened array.

        Return:
        -------
        parameters : ndarray, shape (n_parameters,)
            The computed coefficients by the solver.
        """
        ...

    @classproperty
    def package_import(cls):
        """Hook to override the name of the import in python

        package_import default to package_name."""
        if cls.install_cmd == 'pip':
            return cls.package_name
        raise RuntimeError("This property should only be accessed when "
                           "install_cmd='pip'. Here, install_cmd={}"
                           .format(cls.install_cmd))

    @classproperty
    def package_install(cls):
        """Hook to override the install name for pip.

        package_install default to package_name."""
        if cls.install_cmd == 'pip':
            return cls.package_name
        raise RuntimeError("This property should only be accessed when "
                           "install_cmd='pip'. Here, install_cmd={}"
                           .format(cls.install_cmd))

    @classmethod
    def is_installed(cls, env_name=None):
        if cls.install_cmd == 'pip':
            return check_import_solver(cls.package_import, env_name=env_name)
        elif cls.install_cmd == 'bash':
            return check_cmd_solver(cls.cmd_name, env_name=env_name)
        return True

    @classmethod
    def install(cls, env_name=None, force=False):
        """Install the solver in the given virtual env.

        Parameters
        ----------
        env_name: str or None
            Name of the environment where the solver should be installed. If
            None, tries to install it in the current environment.
        force : boolean (default: False)
            If set to True, first tries to uninstall the solver from the
            environment before installing it.

        Return
        ------
        is_installed: bool
            True if the solver is correctly installed in the environment.
        """
        # uninstall the solvers that requires a force reinstall
        if force:
            cls.uninstall(env_name=env_name)

        if force or not cls.is_installed(env_name=env_name):
            print(f"Installing solver {cls.name} in {env_name}:...",
                  end='', flush=True)
            if cls.install_cmd == 'pip':
                pip_install_in_env(cls.package_install, env_name=env_name)
            elif cls.install_cmd == 'bash':
                bash_install_in_env(cls.install_script, env_name=env_name)
            print(" done")
        return cls.is_installed(env_name=env_name)

    @classmethod
    def uninstall(cls, env_name=None):
        print(f"Uninstalling solver {cls.name} in {env_name}:...",
              end='', flush=True)
        if cls.install_cmd == 'pip':
            pip_uninstall_in_env(cls.package_name, env_name=env_name)
        # elif cls.install_cmd == 'bash':
        #     raise NotImplementedError("Uninstall not implemented for bash.")
        print(" done")

    def _time_run(self, sample):
        """Called by the runner to evaluate the duration of a sample_run.

        """
        t_start = time.time()
        self.run(sample)
        return time.time() - t_start


class CommandLineSolver(BaseSolver, ABC):
    """A base class for solvers that are called through command lines

    Solvers that derive from this class should implement three methods:

    - get_command_line(self, n_iter, lmbd, data_file): a method that returns
      the command line necessary to run the solver up to n_iter with the input
      data provided in data_file.

    - dump_objective(self, X, y): dumps the parameter to compute the objective
      function in a file and returns the name of the file. This utility is
      necessary to reduce the impact of dumping the data to the disk in the
      benchmark.

    - get_result(self): retrieves the result from the disk. This utility is
      necessary to reduce the impact of loading the data from the disk in the
      benchmark.

    """
    def __init__(self, **parameters):
        self._data_file = tempfile.NamedTemporaryFile()
        self._model_file = tempfile.NamedTemporaryFile()
        self.data_filename = self._data_file.name
        self.model_filename = self._model_file.name
        super().__init__(**parameters)

    @abstractmethod
    def get_command_line(self, n_iter):
        """Returns the command line to call the solver for n_iter on data_file

        Parameters
        ----------
        n_iter : int
            Number of iteration to run the solver for. It allows to sample the
            time/accuracy curve in the benchmark.

        Return
        ------
        cmd_line : str
            The command line to call to run the solver for n_iter
        """
        ...

    @abstractmethod
    def dump_objective(self, objective_parameters):
        """Dump the data for the objective to the disk.

        If possible, the data should be dump to the file self.data_filename so
        it will be clean up automatically by benchopt.

        Parameters
        ----------
        objective_parameters: tuple
            Parameter to construct the objective function. The specific shape
            and the order of the parameter are described in each benchmark
            definition file.
        """
        ...

    @abstractmethod
    def get_result(self):
        """Load the data from the disk and return the coefficients

        If possible, the model should be loaded from self.model_filename so
        it will be clean up automatically by benchopt.

        Return:
        -------
        parameters : ndarray, shape (n_parameters,)
            The computed coefficients by the solver.
        """
        ...

    def set_objective(self, **objective_parameters):
        """Prepare the data"""
        self.dump_objective(**objective_parameters)

    def _time_run(self, sample):
        """Called by the runner to evaluate the duration of a sample_run.

        Here, we do something a bit more complicated to mitigate the overhead
        due to the file I/O for the

        """
        # trace_cmd_line = (f"strace -cP {self.data_filename} "
        #                   f"-P {self.model_filename}")
        trace_cmd_line = "/usr/bin/time --format=%e\t%S\t%U"
        solver_cmd_line = self.get_command_line(sample)
        cmd_line = f"{trace_cmd_line} {solver_cmd_line}".split(' ')

        t_start = time.time()
        output = subprocess.check_output(
            cmd_line, stderr=subprocess.STDOUT
        )
        delta_t = time.time() - t_start
        wall_times = re.findall(r'([0-9.]*)\t*([0-9.]*)\t([0-9.]*)',
                                output.decode())[0]
        total_time, sys_time, usr_time = [float(t) for t in wall_times]
        io_time = total_time - (sys_time + usr_time)
        # time_io = re.findall(r'([0-9.]*)\s*[0-9]*\s*total$', output.decode())
        # assert len(time_io) == 1
        # time_io = float(time_io[0])

        return delta_t - io_time

    def run(self, sample):
        solver_cmd_line = self.get_command_line(sample).split(' ')
        subprocess.check_call(solver_cmd_line)


class BaseDataset(ParametrizedNameMixin):
    """Base class to define a dataset in a benchmark.
    """

    @abstractmethod
    def get_data(self):
        """Return the scale of the problem as well as the objective parameters.

        Return
        ------
        scale: int
            Size of the optimized parameter. The solvers should return a
            parameter of shape (scale,).
        data: dict
            Extra parameters of the objective. The objective will be
            instanciated by calling Objective.set_data(**data)
        """
        ...


class BaseObjective(ParametrizedNameMixin):
    """Base class to define an objective
    """
    def __init__(self, **parameters):
        """Instantiate a solver with the given parameters and store them.

        All parameters `PARAM` that are passed through init will be accessible
        as `self.PARAM` in the class.
        """
        super().__init__(**parameters)
        for k, v in parameters.items():
            setattr(self, k, v)

    @abstractmethod
    def __call__(self, beta):
        ...

    @abstractmethod
    def set_data(self, **data):
        ...

    @abstractmethod
    def to_dict(self):
        ...
