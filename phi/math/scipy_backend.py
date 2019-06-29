from phi.math.base import Backend
import numpy as np
import numbers
import collections
import scipy.sparse, scipy.signal

class SciPyBackend(Backend):

    def __init__(self):
        Backend.__init__(self, "SciPy")

    def is_applicable(self, values):
        if values is None: return True
        if isinstance(values, np.ndarray): return True
        if isinstance(values, numbers.Number): return True
        if isinstance(values, bool): return True
        if scipy.sparse.issparse(values): return True
        if isinstance(values, collections.Iterable):
            try:
                for value in values:
                    if not self.is_applicable(value): return False
                return True
            except:
                return False
        return False

    def rank(self, value):
        return len(value.shape)

    def range(self, limit, start=0, delta=1, dtype=None):
        return np.arange(start, limit, delta, dtype)

    def tile(self, value, multiples):
        return np.tile(value, multiples)

    def stack(self, values, axis=0):
        return np.stack(values, axis)

    def concat(self, values, axis):
        return np.concatenate(values, axis)

    def pad(self, value, pad_width, mode="constant", constant_values=0):
        if np.sum(np.array(pad_width)) == 0:
            return value
        if mode.lower() == "constant":
            return np.pad(value, pad_width, "constant", constant_values=constant_values)
        else:
            return np.pad(value, pad_width, mode.lower())

    def add(self, values):
        return np.sum(values, axis=0)

    def reshape(self, value, shape):
        return value.reshape(shape)

    def sum(self, value, axis=None):
        return np.sum(value, axis=axis)

    def prod(self, value, axis=None):
        if value.dtype == bool:
            return np.all(value, axis=axis)
        return np.prod(value, axis=axis)

    def where(self, condition, x=None, y=None):
        if x is None or y is None:
            return np.where(condition)
        return np.where(condition, x, y)

    def py_func(self, func, inputs, Tout, shape_out, stateful=True, name=None, grad=None):
        result = func(*inputs)
        assert result.dtype == Tout, "returned value has wrong type: {}, expected {}".format(result.dtype, Tout)
        assert result.shape == shape_out, "returned value has wrong shape: {}, expected {}".format(result.shape,
                                                                                                   shape_out)
        return result

    def resample(self, inputs, sample_coords, interpolation="LINEAR", boundary="ZERO"):
        if boundary.lower() == "zero":
            pass # default
        elif boundary.lower() == "replicate":
            sample_coords = clamp(sample_coords, inputs.shape[1:-1])
        elif boundary.lower() == "updim":
            dimensions = inputs.shape[1:-1]
            rank = len(dimensions)
            if rank == 1:
                updim = 0
            else:
                updim = rank - 2
            # Zero boundary resample in positive upper dimension, replicate resample for all other dimensions.
            # Adding 1 will allow out of bounds resample, which results to a zero value.
            dimensions = np.array(dimensions)
            dimensions[updim] = dimensions[updim] + 1
            sample_coords = clamp(sample_coords, dimensions)
        else:
            raise ValueError("Unsupported boundary: %s"%boundary)

        # if interpolation.lower() == "sigmoid":            
        #     def sigmoid(x):
        #         x_sc = 10.0
        #         x_tr = 0.5
        #         b = (np.exp(x_sc * (1 - x_tr)) + 1) / (1 - np.exp(x_sc))
        #         a = -b * (1 + np.exp(x_sc * x_tr))
                
        #         return b + a / (1 + np.exp(-x_sc * (x - x_tr)))

        #     diff = sample_coords - np.floor(sample_coords)
        #     sample_coords = np.floor(sample_coords) + sigmoid(diff)
        #     interpolation = "linear"
        
        import scipy.interpolate
        points = [np.arange(dim) for dim in inputs.shape[1:-1]]
        result = []
        for batch in range(sample_coords.shape[0]):
            components = []
            for dim in range(inputs.shape[-1]):
                resampled = scipy.interpolate.interpn(points, inputs[batch, ..., dim], sample_coords[batch, ...],
                                         method=interpolation.lower(), bounds_error=False, fill_value=0)
                components.append(resampled)
            result.append(np.stack(components, -1))

        result = np.stack(result).astype(inputs.dtype)
        return result

    def zeros_like(self, tensor):
        return np.zeros_like(tensor)

    def ones_like(self, tensor):
        return np.ones_like(tensor)

    def mean(self, value, axis=None):
        return np.mean(value, axis)

    def dot(self, a, b, axes):
        return np.tensordot(a, b, axes)

    def matmul(self, A, b):
        return np.stack([A.dot(b[i]) for i in range(b.shape[0])])

    def while_loop(self, cond, body, loop_vars, shape_invariants=None, parallel_iterations=10, back_prop=True,
                   swap_memory=False, name=None, maximum_iterations=None):
        i = 0
        while cond(*loop_vars):
            if maximum_iterations is not None and i == maximum_iterations: break
            loop_vars = body(*loop_vars)
            i += 1
        return loop_vars

    def abs(self, x):
        return np.abs(x)

    def sign(self, x):
        return np.sign(x)

    def round(self, x):
        return np.round(x)

    def ceil(self, x):
        return np.ceil(x)

    def floor(self, x):
        return np.floor(x)

    def max(self, x, axis=None):
        return np.max(x, axis)

    def with_custom_gradient(self, function, inputs, gradient, input_index=0, output_index=None, name_base="custom_gradient_func"):
        return function(*inputs)

    def maximum(self, a, b):
        return np.maximum(a, b)

    def minimum(self, a, b):
        return np.minimum(a, b)

    def sqrt(self, x):
        return np.sqrt(x)

    def exp(self, x):
        return np.exp(x)

    def conv(self, tensor, kernel, padding="SAME"):
        assert tensor.shape[-1] == kernel.shape[-2]
        # kernel = kernel[[slice(None)] + [slice(None, None, -1)] + [slice(None)]*(len(kernel.shape)-3) + [slice(None)]]
        if padding.lower() == "same":
            result = np.zeros(tensor.shape[:-1]+(kernel.shape[-1],), np.float32)
        elif padding.lower() == "valid":
            valid = [tensor.shape[i+1]-(kernel.shape[i]+1)//2 for i in range(tensor_spatial_rank(tensor))]
            result = np.zeros([tensor.shape[0]]+valid+[kernel.shape[-1]], np.float32)
        else:
            raise ValueError("Illegal padding: %s"%padding)
        for batch in range(tensor.shape[0]):
            for o in range(kernel.shape[-1]):
                for i in range(tensor.shape[-1]):
                    result[batch, ..., o] += scipy.signal.correlate(tensor[batch, ..., i], kernel[..., i, o], padding.lower())
        return result

    def expand_dims(self, a, axis=0):
        return np.expand_dims(a, axis)

    def shape(self, tensor):
        return tensor.shape

    def to_float(self, x):
        return np.array(x).astype(np.float32)

    def to_int(self, x, int64=False):
        return np.array(x).astype(np.int64 if int64 else np.int32)

    def gather(self, values, indices):
        return values[indices]

    def gather_nd(self, values, indices):
        return values[indices]

    def unstack(self, tensor, axis=0):
        if axis < 0:
            axis += len(tensor.shape)
        if axis >= len(tensor.shape) or axis < 0:
            raise ValueError("Illegal axis value")
        result = []
        for i in range(tensor.shape[axis]):
            result.append(tensor[[i if d==axis else slice(None) for d in range(len(tensor.shape))]])
        return result

    def std(self, x, axis=None):
        return np.std(x, axis)

    def boolean_mask(self, x, mask):
        return x[mask]

    def isfinite(self, x):
        return np.isfinite(x)

    def any(self, boolean_tensor, axis=None, keepdims=False):
        return np.any(boolean_tensor, axis=axis, keepdims=keepdims)

    def all(self, boolean_tensor, axis=None, keepdims=False):
        return np.all(boolean_tensor, axis=axis, keepdims=keepdims)

    def scatter(self, indices, values, shape, duplicates_handling='undefined'):
        indices = self.unstack(indices, axis=-1)
        array = np.zeros(shape, np.float32)
        if duplicates_handling == 'add':
            np.add.at(array, indices, values)
        elif duplicates_handling == 'mean':
            count = np.zeros(shape, np.int32)
            np.add.at(array, indices, values)
            np.add.at(count, indices, 1)
            count = np.maximum(1, count)
            return array / count
        else: # last, any, undefined
            array[indices] = values
        return array


def clamp(coordinates, shape):
    assert coordinates.shape[-1] == len(shape)
    for i in range(len(shape)):
        coordinates[...,i] = np.maximum(0, np.minimum(shape[i]-1, coordinates[...,i]))
    return coordinates


def tensor_spatial_rank(field):
    dims = len(field.shape) - 2
    assert dims > 0, "channel has no spatial dimensions"
    return dims


def as_tensor(x):
    if isinstance(x, (list, tuple)):
        return np.array(x)
    else:
        return x