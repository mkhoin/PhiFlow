import warnings

from phi import struct
from .field import advect
from .field.effect import effect_applied
from .field.util import diffuse
from .domain import DomainState
from .physics import Physics, StateDependency


@struct.definition()
class DiffusiveVelocity(DomainState):

    def __init__(self, domain, velocity, viscosity=0.1, **kwargs):
        DomainState.__init__(self, **struct.kwargs(locals()))

    @struct.variable(dependencies=DomainState.domain)
    def velocity(self, velocity):
        return self.centered_grid('velocity', velocity, self.rank)

    @struct.constant()
    def viscosity(self, viscosity):
        return viscosity


class Burgers(Physics):

    def __init__(self, default_viscosity=0.1, viscosity=None):
        Physics.__init__(self, [StateDependency('effects', 'velocity_effect', blocking=True)])
        if viscosity is not None:
            warnings.warn("Argument 'viscosity' is deprecated, use 'default_viscosity' instead.", DeprecationWarning)
            default_viscosity = viscosity
        self.default_viscosity = default_viscosity

    def step(self, v, dt=1.0, effects=()):
        if isinstance(v, DiffusiveVelocity):
            return v.copied_with(velocity=self.step_velocity(v.velocity, v.viscosity, dt, effects), age=v.age+dt)
        else:
            return self.step_velocity(v, self.default_viscosity, dt, effects)

    @staticmethod
    def step_velocity(v, viscosity, dt, effects):
        v = advect.semi_lagrangian(v, v, dt)
        v = diffuse(v, dt * viscosity, substeps=1)
        for effect in effects:
            v = effect_applied(effect, v, dt)
        return v.copied_with(age=v.age + dt)
