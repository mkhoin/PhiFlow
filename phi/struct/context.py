from contextlib import contextmanager


_STRUCT_CONTEXT_STACK = []


@contextmanager
def _struct_context(object):
    _STRUCT_CONTEXT_STACK.append(object)
    try:
        yield None
    finally:
        _STRUCT_CONTEXT_STACK.pop(-1)


def unsafe():
    return _struct_context('unsafe')


def only(item_type):
    return _struct_context(_ItemTypeContext(item_type))


def skip_validate():
    return 'unsafe' in _STRUCT_CONTEXT_STACK


def context_item_condition(item):
    for context in _STRUCT_CONTEXT_STACK:
        if isinstance(context, _ItemTypeContext):
            if not context.condition_check(item):
                return False
    return True


class _ItemTypeContext(object):

    def __init__(self, item_condition):
        assert item_condition is None or callable(item_condition), item_condition
        self.item_condition = item_condition

    def condition_check(self, item):
        if self.item_condition is None:
            return True
        else:
            return self.item_condition(item)

    def __repr__(self):
        return 'Only_%s' % (self.item_condition.__name__ if callable(self.item_condition) else self.item_condition)
