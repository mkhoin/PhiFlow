import logging
from numbers import Number
import numpy as np
import scipy
import scipy.sparse
import scipy.sparse.linalg

from phi import math
from phi.math.blas import conjugate_gradient
from phi.struct.tensorop import collapsed_gather_nd
from .solver_api import PressureSolver, FluidDomain


class SparseSciPy(PressureSolver):

    def __init__(self):
        """
        The SciPy solver uses the function scipy.sparse.linalg.spsolve to determine the pressure.
        It does not support initial guesses for the pressure and does not keep track of a loop counter.
        """
        PressureSolver.__init__(self, 'SciPy sparse solver',
                                supported_devices=('CPU',),
                                supports_guess=False, supports_loop_counter=False, supports_continuous_masks=True)

    def solve(self, divergence, domain, pressure_guess):
        assert isinstance(domain, FluidDomain)
        dimensions = list(divergence.shape[1:-1])
        A = sparse_pressure_matrix(dimensions, domain.active_tensor(extend=1), domain.accessible_tensor(extend=1))

        def np_solve_p(div):
            div_vec = div.reshape([-1, A.shape[0]])
            pressure = [scipy.sparse.linalg.spsolve(A, div_vec[i, ...]) for i in range(div_vec.shape[0])]
            return np.array(pressure).reshape(div.shape).astype(np.float32)

        def np_solve_p_gradient(op, grad_in):
            return math.py_func(np_solve_p, [grad_in], np.float32, divergence.shape)

        pressure = math.py_func(np_solve_p, [divergence], np.float32, divergence.shape, grad=np_solve_p_gradient)
        return pressure, None


class SparseCG(PressureSolver):

    def __init__(self, accuracy=1e-5, gradient_accuracy='same',
                 max_iterations=2000, max_gradient_iterations='same',
                 autodiff=False):
        """
        Conjugate gradient solver using sparse matrix multiplications.

        :param accuracy: the maximally allowed error on the divergence channel for each cell
        :param gradient_accuracy: accuracy applied during backpropagation, number of 'same' to use forward accuracy
        :param max_iterations: integer specifying maximum conjugent gradient loop iterations or None for no limit
        :param max_gradient_iterations: maximum loop iterations during backpropagation,
            'same' uses the number from max_iterations,
            'mirror' sets the maximum to the number of iterations that were actually performed in the forward pass
        :param autodiff: If autodiff=True, use the built-in autodiff for backpropagation.
            The intermediate results of each loop iteration will be permanently stored if backpropagation is used.
            If False, replaces autodiff by a forward pressure solve in reverse accumulation backpropagation.
            This requires less memory but is only accurate if the solution is fully converged.
        """
        PressureSolver.__init__(self, 'Sparse Conjugate Gradient',
                                supported_devices=('CPU', 'GPU'),
                                supports_guess=True, supports_loop_counter=True, supports_continuous_masks=True)
        assert isinstance(accuracy, Number), 'invalid accuracy: %s' % accuracy
        assert gradient_accuracy == 'same' or isinstance(gradient_accuracy, Number), 'invalid gradient_accuracy: %s' % gradient_accuracy
        assert max_gradient_iterations in ['same', 'mirror'] or isinstance(max_gradient_iterations, Number), 'invalid max_gradient_iterations: %s' % max_gradient_iterations
        self.accuracy = accuracy
        self.gradient_accuracy = accuracy if gradient_accuracy == 'same' else gradient_accuracy
        self.max_iterations = max_iterations
        if max_gradient_iterations == 'same':
            self.max_gradient_iterations = max_iterations
        elif max_gradient_iterations == 'mirror':
            self.max_gradient_iterations = 'mirror'
        else:
            self.max_gradient_iterations = max_gradient_iterations
            assert not autodiff, 'Cannot specify max_gradient_iterations when autodiff=True'
        self.autodiff = autodiff

    def solve(self, divergence, domain, pressure_guess):
        assert isinstance(domain, FluidDomain)
        active_mask = domain.active_tensor(extend=1)
        fluid_mask = domain.accessible_tensor(extend=1)
        dimensions = math.staticshape(divergence)[1:-1]
        N = int(np.prod(dimensions))

        A = sparse_pressure_matrix(dimensions, active_mask, fluid_mask)
        if not math.choose_backend(divergence).matches_name('SciPy'):
            A = A.tocoo()
            A = math.choose_backend(divergence).sparse_tensor(indices=math.stack([A.col, A.row], axis=-1), values=A.data, shape=[N, N])

        if self.autodiff:
            return sparse_cg(divergence, A, self.max_iterations, pressure_guess, self.accuracy, back_prop=True)
        else:
            def pressure_gradient(op, grad):
                return sparse_cg(grad, A, max_gradient_iterations, None, self.gradient_accuracy)[0]

            pressure, iteration = math.with_custom_gradient(sparse_cg,
                                                            [divergence, A, self.max_iterations, pressure_guess, self.accuracy],
                                                            pressure_gradient, input_index=0, output_index=0,
                                                            name_base='scg_pressure_solve')

            max_gradient_iterations = iteration if self.max_gradient_iterations == 'mirror' else self.max_gradient_iterations
            return pressure, iteration


def sparse_cg(divergence, A, max_iterations, guess, accuracy, back_prop=False):
    div_vec = math.reshape(divergence, [-1, int(np.prod(divergence.shape[1:]))])
    if guess is not None:
        guess = math.reshape(guess, [-1, int(np.prod(divergence.shape[1:]))])
    apply_A = lambda pressure: math.matmul(A, pressure)
    result_vec, iterations = conjugate_gradient(div_vec, apply_A, guess, accuracy, max_iterations, back_prop)
    return math.reshape(result_vec, math.shape(divergence)), iterations


def sparse_pressure_matrix(dimensions, extended_active_mask, extended_fluid_mask, periodic=False):
    """
    Builds a sparse matrix such that when applied to a flattened pressure channel, it calculates the laplace
    of that channel, taking into account obstacles and empty cells.

    :param dimensions: valid simulation dimensions. Pressure channel should be of shape (batch size, dimensions..., 1)
    :param extended_active_mask: Binary tensor with 2 more entries in every dimension than 'dimensions'.
    :param extended_fluid_mask: Binary tensor with 2 more entries in every dimension than 'dimensions'.
    :return: SciPy sparse matrix that acts as a laplace on a flattened pressure channel given obstacles and empty cells
    """
    N = int(np.prod(dimensions))
    d = len(dimensions)
    A = scipy.sparse.lil_matrix((N, N), dtype=np.float32)
    dims = range(d)

    diagonal_entries = np.zeros(N, extended_active_mask.dtype)  # diagonal matrix entries

    gridpoints_linear = np.arange(N)
    gridpoints = np.stack(np.unravel_index(gridpoints_linear, dimensions))  # d * (N^2) array mapping from linear to spatial frames

    for dim in dims:
        upper_indices = tuple([slice(None)] + [slice(2, None) if i == dim else slice(1, -1) for i in dims] + [slice(None)])
        center_indices = tuple([slice(None)] + [slice(1, -1) if i == dim else slice(1, -1) for i in dims] + [slice(None)])
        lower_indices = tuple([slice(None)] + [slice(0, -2) if i == dim else slice(1, -1) for i in dims] + [slice(None)])

        self_active = extended_active_mask[center_indices]
        stencil_upper = extended_active_mask[upper_indices] * self_active
        stencil_lower = extended_active_mask[lower_indices] * self_active
        stencil_center = - extended_fluid_mask[upper_indices] - extended_fluid_mask[lower_indices]

        diagonal_entries += math.flatten(stencil_center)

        # Find entries in matrix
        dim_direction = math.expand_dims([1 if i == dim else 0 for i in range(d)], axis=-1)
        # Upper frames
        upper_points, upper_idx = wrap_or_discard(gridpoints + dim_direction, dim, dimensions, periodic=collapsed_gather_nd(periodic, [dim, 1]))
        A[gridpoints_linear[upper_idx], upper_points] = stencil_upper.flatten()[upper_idx]
        # Lower frames
        lower_points, lower_idx = wrap_or_discard(gridpoints - dim_direction, dim, dimensions, periodic=collapsed_gather_nd(periodic, [dim, 0]))
        A[gridpoints_linear[lower_idx], lower_points] = stencil_lower.flatten()[lower_idx]

    A[gridpoints_linear, gridpoints_linear] = math.minimum(diagonal_entries, -1)  # avoid 0, could lead to NaN

    return scipy.sparse.csc_matrix(A)


def wrap_or_discard(indices, dim, dimensions, periodic=False):
    upper_in_range_inx = np.nonzero((indices[dim] < dimensions[dim]) & (indices[dim] >= 0))
    indices_linear = np.ravel_multi_index(indices[:, upper_in_range_inx], dimensions)
    return indices_linear, upper_in_range_inx
