from phi.math import batch_align
from phi.struct import Trait, Struct, definition, constant
from .base_backend import DYNAMIC_BACKEND as math


class Batched(Trait):

    def endow(self, struct):
        struct.batch_size = None

    def pre_validated(self, struct, item, value):
        tensor = math.as_tensor(value)
        # return batch_align
        return tensor

    def post_validate_struct(self, struct):
        for item in struct.__items__:
            if self in item.traits:
                print(item)
        pass  # Todo check all items with dims and their alignment


BATCHED = Batched(keywords=['dims'])


@definition(traits=[BATCHED])
class BatchedStruct(Struct):

    @constant()
    def batch_size(self, batch_size):
        assert isinstance(batch_size, int) or batch_size is None
        return batch_size
