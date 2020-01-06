from phi import struct
from phi.struct import Trait, Struct, definition, constant, derived
from .base_backend import DYNAMIC_BACKEND as math


class Shaped(Trait):

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


SHAPED = Shaped(keywords=['dims'])


@definition(traits=[SHAPED])
class ShapedStruct(Struct):

    @struct.derived()
    def shape(self):
        return None

    @struct.derived()
    def staticshape(self):
        return None


def _shape(obj):
    if isinstance(obj, ShapedStruct):
        result = obj.shape
    elif struct.isstruct(obj):
        with struct.unsafe():
            result = struct.map(_shape, obj, recursive=False, item_condition=struct.VARIABLES)
    else:
        result = math.shape(obj)
    return result
