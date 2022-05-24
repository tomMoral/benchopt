from pathlib import Path

from benchopt.helpers.r_lang import RSolver
from benchopt import safe_import_context


with safe_import_context() as import_ctx:
    import numpy as np
    from rpy2 import robjects
    from benchopt.helpers.r_lang import import_func_from_r_file


R_FILE = str(Path(__file__).with_suffix('.R'))


class Solver(RSolver):
    name = "R-PGD"

    stopping_strategy = 'iteration'

    def set_objective(self, X, y, lmbd):
        # Store X as a sparse matrix if needed
        self.store_matrix(X)
        self.y, self.lmbd = y, lmbd

        # Import R function defined in r_pgd.R so they can be retrieved as
        # python function
        import_func_from_r_file(R_FILE)
        self.r_pgd = robjects.r['proximal_gradient_descent']

    def run(self, n_iter):
        coefs = self.r_pgd(self.X, self.y[:, None], self.lmbd, n_iter=n_iter)
        self.w = np.asarray(coefs)

    def get_result(self):
        return self.w.flatten()
