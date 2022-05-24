import os
import timeit
from pathlib import Path

from benchopt import BaseSolver, safe_import_context

# Make sure that R_HOME is loaded from the current interpreter to avoid
# using the parent interpreter R_HOME in the sub-interpreter.
if os.environ.get('R_HOME', None) is not None:
    del os.environ['R_HOME']


with safe_import_context() as import_ctx:
    from scipy import sparse

    from rpy2 import robjects
    from rpy2.robjects import numpy2ri, packages

    # Setup the system to allow rpy2 running
    numpy2ri.activate()

    import rpy2
    import rpy2.robjects.packages as rpackages
    import rpy2.situation

    try:
        from rpy2.robjects.packages import PackageNotInstalledError
    except ImportError:
        # Backward compat for rpy2 version < 3.3
        try:
            from rpy2.rinterface_lib.embedded import \
                RRuntimeError as PackageNotInstalledError
        except ImportError:
            # Backward compat for rpy2 version < 3
            from rpy2.rinterface import RRuntimeError
            PackageNotInstalledError = RRuntimeError

    # Hide the R warnings
    rpy2.robjects.r['options'](warn=-1)

    # Set the R_HOME directory to the one of the R RHOME ouput
    os.environ['R_HOME'] = rpy2.situation.r_home_from_subprocess()

    def import_rpackages(*packages):
        """Helper to import R packages in the import_ctx"""
        for pkg in packages:
            try:
                rpackages.importr(pkg)
            except PackageNotInstalledError:
                raise ImportError(f"R package '{pkg}' is not installed")

    def import_func_from_r_file(filename):
        r_source = robjects.r['source']
        r_source(str(filename))


class RSolver(BaseSolver):

    # Requirements
    install_cmd = 'conda'
    requirements = ['r-base', 'rpy2', 'r-matrix']

    def store_matrix(self, X):
        if sparse.issparse(X):
            r_Matrix = packages.importr("Matrix")
            X = X.tocoo()
            self.X = r_Matrix.sparseMatrix(
                i=robjects.IntVector(X.row + 1),
                j=robjects.IntVector(X.col + 1),
                x=robjects.FloatVector(X.data),
                dims=robjects.IntVector(X.shape)
            )
        else:
            self.X = X

    def evaluate_overhead(self, *args, **kwargs):
        import_func_from_r_file(Path(__file__).with_suffix(".r"))
        empty_run = robjects.r['empty_run']

        n, t = timeit.Timer(lambda: empty_run(*args, **kwargs)).autorange()
        self._empty_run_overhead = t / n
