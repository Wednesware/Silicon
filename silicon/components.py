"""Composable, serializable gameplay helpers; all mutable values are game scoped."""
import math

from . import Component, State, input, output, register, update


def _number(value, name='value'):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return value


@register('silicon.Transform2D')
class Transform2D(Component):
    positions = State({}, scope='game')

    @input
    def place(self, entity: str, x, y):
        x, y = _number(x), _number(y)
        self.positions = {**self.positions, entity: [x, y]}
        self.out.moved(entity, x, y)

    @input
    def move(self, entity: str, dx, dy):
        x, y = self.positions[entity]
        self.place(entity, x + _number(dx), y + _number(dy))

    @input
    def remove(self, entity: str):
        self.positions = {k: v for k, v in self.positions.items() if k != entity}
        self.out.removed(entity)

    @output
    def moved(self, entity: str, x: float, y: float): pass

    @output
    def removed(self, entity: str): pass


@register('silicon.Velocity')
class Velocity(Component):
    velocities = State({}, scope='game')

    def __init__(self, transform_id='transform'):
        super().__init__()
        self.transform_id = transform_id

    def to_config(self): return {'transform_id': self.transform_id}

    @input
    def set(self, entity: str, x, y):
        self.velocities = {**self.velocities, entity: [_number(x), _number(y)]}

    @input
    def accelerate(self, entity: str, x, y):
        vx, vy = self.velocities.get(entity, [0.0, 0.0])
        self.set(entity, vx + _number(x), vy + _number(y))

    @input
    def stop(self, entity: str):
        self.velocities = {k: v for k, v in self.velocities.items() if k != entity}

    @update()
    def advance(self, dt):
        game = self._active_game
        positions = game[self.transform_id].state.positions
        for entity, (vx, vy) in tuple(self.velocities.items()):
            if entity in positions:
                game[self.transform_id].ins.move(entity, vx * dt, vy * dt)


@register('silicon.Gravity')
class Gravity(Component):
    """Add before Velocity for semi-implicit Euler integration; positive y is down."""
    entities = State([], scope='game')

    def __init__(self, acceleration=9.8, velocity_id='velocity', terminal_speed=None):
        super().__init__()
        self.acceleration = _number(acceleration)
        self.velocity_id = velocity_id
        self.terminal_speed = None if terminal_speed is None else _number(terminal_speed)
        if self.terminal_speed is not None and self.terminal_speed < 0:
            raise ValueError('terminal_speed must be nonnegative')

    def to_config(self):
        return dict(acceleration=self.acceleration, velocity_id=self.velocity_id,
                    terminal_speed=self.terminal_speed)

    @input
    def add(self, entity: str):
        if entity not in self.entities:
            self.entities = [*self.entities, entity]

    @input
    def remove(self, entity: str):
        self.entities = [e for e in self.entities if e != entity]

    @update()
    def advance(self, dt):
        velocity = self._active_game[self.velocity_id]
        for entity in tuple(self.entities):
            vx, vy = velocity.state.velocities.get(entity, [0.0, 0.0])
            vy += self.acceleration * dt
            if self.terminal_speed is not None:
                vy = max(-self.terminal_speed, min(self.terminal_speed, vy))
            velocity.ins.set(entity, vx, vy)


@register('silicon.InputMap')
class InputMap(Component):
    def __init__(self, bindings=None):
        super().__init__()
        self.bindings = dict(bindings if bindings is not None else {
            'w': 'up', 'ArrowUp': 'up', 's': 'down', 'ArrowDown': 'down',
            'a': 'left', 'ArrowLeft': 'left', 'd': 'right', 'ArrowRight': 'right'})

    def to_config(self): return {'bindings': self.bindings}

    @input
    def feed(self, key: str):
        if key in self.bindings:
            self.out.action(self.bindings[key])
            return True
        self.out.unknown(key)
        return False

    @output
    def action(self, name: str): pass

    @output
    def unknown(self, key: str): pass


@register('silicon.GridMovement')
class GridMovement(Component):
    """Move a selected Stage2D entity; walls and occupied solid cells block movement."""
    solids = State([], scope='game')

    def __init__(self, entity='hero', stage_id='stage'):
        super().__init__()
        self.entity, self.stage_id = entity, stage_id

    def to_config(self): return dict(entity=self.entity, stage_id=self.stage_id)

    @input
    def command(self, direction: str):
        deltas = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}
        if direction not in deltas:
            return False
        return self.move(*deltas[direction])

    @input
    def move(self, dx: int, dy: int):
        game = self._active_game
        stage = game.get(self.stage_id)
        cells = game[stage].state.cells
        x, y = cells[self.entity]
        x, y = x + dx, y + dy
        occupied = any(e != self.entity and e in self.solids and p == [x, y]
                       for e, p in cells.items())
        if not (0 <= x < stage.width and 0 <= y < stage.height) or occupied:
            self.out.blocked(self.entity, x, y)
            return False
        game[stage].ins.move(self.entity, x, y)
        self.out.moved(self.entity, x, y)
        return True

    @input
    def solid(self, entity: str):
        if entity not in self.solids:
            self.solids = [*self.solids, entity]

    @output
    def moved(self, entity: str, x: int, y: int): pass

    @output
    def blocked(self, entity: str, x: int, y: int): pass


@register('silicon.Collision2D')
class Collision2D(Component):
    """AABB overlap events (detection only); touching edges do not overlap."""
    sizes = State({}, scope='game')
    contacts = State([], scope='game')

    def __init__(self, transform_id='transform'):
        super().__init__()
        self.transform_id = transform_id

    def to_config(self): return {'transform_id': self.transform_id}

    @input
    def add(self, entity: str, width=1, height=1):
        width, height = _number(width), _number(height)
        if width <= 0 or height <= 0:
            raise ValueError('Collider sizes must be positive')
        self.sizes = {**self.sizes, entity: [width, height]}

    @input
    def remove(self, entity: str):
        self.sizes = {k: v for k, v in self.sizes.items() if k != entity}

    @update()
    def check(self, dt):
        positions = self._active_game[self.transform_id].state.positions
        entities = sorted(set(positions) & set(self.sizes))
        contacts = []
        for i, a in enumerate(entities):
            ax, ay = positions[a]
            aw, ah = self.sizes[a]
            for b in entities[i + 1:]:
                bx, by = positions[b]
                bw, bh = self.sizes[b]
                if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                    contacts.append([a, b])
        old = self.contacts
        self.contacts = contacts
        for pair in contacts:
            if pair not in old:
                self.out.entered(*pair)
        for pair in old:
            if pair not in contacts:
                self.out.exited(*pair)

    @output
    def entered(self, first: str, second: str): pass

    @output
    def exited(self, first: str, second: str): pass


@register('silicon.Health')
class Health(Component):
    values = State({}, scope='game')
    maximums = State({}, scope='game')

    @input
    def add(self, entity: str, maximum=3):
        maximum = _number(maximum)
        if maximum <= 0:
            raise ValueError('maximum must be positive')
        self.maximums = {**self.maximums, entity: maximum}
        self.values = {**self.values, entity: maximum}
        self.out.changed(entity, maximum)

    @input
    def damage(self, entity: str, amount=1):
        amount = _number(amount)
        if amount < 0:
            raise ValueError('amount must be nonnegative')
        old = self.values[entity]
        value = max(0.0, old - amount)
        self.values = {**self.values, entity: value}
        self.out.changed(entity, value)
        if old > 0 and value == 0:
            self.out.died(entity)

    @input
    def heal(self, entity: str, amount=1):
        amount = _number(amount)
        if amount < 0:
            raise ValueError('amount must be nonnegative')
        value = min(self.maximums[entity], self.values[entity] + amount)
        self.values = {**self.values, entity: value}
        self.out.changed(entity, value)

    @output
    def changed(self, entity: str, value: float): pass

    @output
    def died(self, entity: str): pass


@register('silicon.Inventory')
class Inventory(Component):
    items = State({}, scope='game')

    @input
    def add(self, item: str, count: int = 1):
        if count < 1:
            raise ValueError('count must be positive')
        self.items = {**self.items, item: self.items.get(item, 0) + count}
        self.out.changed(item, self.items[item])

    @input
    def take(self, item: str, count: int = 1):
        if count < 1:
            raise ValueError('count must be positive')
        if self.items.get(item, 0) < count:
            self.out.missing(item)
            return False
        remaining = self.items[item] - count
        self.items = {k: v for k, v in {**self.items, item: remaining}.items() if v}
        self.out.changed(item, remaining)
        return True

    @output
    def changed(self, item: str, count: int): pass

    @output
    def missing(self, item: str): pass


@register('silicon.Score')
class Score(Component):
    value = State(0, scope='game')

    @input
    def add(self, amount: int = 1):
        self.value += amount
        self.out.changed(self.value)

    @input
    def reset(self):
        self.value = 0
        self.out.changed(self.value)

    @output
    def changed(self, value: int): pass


@register('silicon.Lifetime')
class Lifetime(Component):
    remaining = State({}, scope='game')

    @input
    def add(self, entity: str, seconds):
        seconds = _number(seconds)
        if seconds < 0:
            raise ValueError('seconds must be nonnegative')
        self.remaining = {**self.remaining, entity: seconds}

    @input
    def remove(self, entity: str):
        self.remaining = {k: v for k, v in self.remaining.items() if k != entity}

    @update()
    def advance(self, dt):
        remaining = {e: t - dt for e, t in self.remaining.items()}
        self.remaining = {e: t for e, t in remaining.items() if t > 0}
        for entity, seconds in remaining.items():
            if seconds <= 0:
                self.out.expired(entity)

    @output
    def expired(self, entity: str): pass


@register('silicon.CommandOptions')
class CommandOptions(Component):
    """Snapshot argv without the executable and query options without a schema.

    Options accept --name=value or --name value. Bare options return True;
    declare known boolean flags to keep them from consuming a positional value.
    Repeated options use the last occurrence, including across queried aliases.
    A standalone -- ends option parsing. Values remain strings.
    """
    def __init__(self, argv=None, flags=None):
        super().__init__()
        if argv is None:
            import sys
            argv = sys.argv[1:]
        if isinstance(argv, str):
            raise TypeError('argv must be a sequence of argument strings')
        self.argv = tuple(argv)
        if not all(isinstance(arg, str) for arg in self.argv):
            raise TypeError('argv must contain strings')
        if isinstance(flags, str):
            raise TypeError('flags must be a sequence of option names')
        self.flags = tuple(flags or ())
        if not all(isinstance(flag, str) and self._is_option(flag) and '=' not in flag
                   for flag in self.flags):
            raise ValueError('flags must contain option names such as --verbose')
        self._options = []
        self._positionals = []
        index = 0
        while index < len(self.argv):
            token = self.argv[index]
            index += 1
            if token == '--':
                self._positionals.extend(self.argv[index:])
                break
            if not self._is_option(token):
                self._positionals.append(token)
                continue
            name, separator, value = token.partition('=')
            if not separator:
                value = True
                if (name not in self.flags and index < len(self.argv)
                        and self.argv[index] != '--'
                        and not self._is_option(self.argv[index])):
                    value = self.argv[index]
                    index += 1
            self._options.append((name, value))

    @staticmethod
    def _is_option(token):
        if not token.startswith('-') or token == '-':
            return False
        try:
            float(token)
        except ValueError:
            return True
        return False

    @property
    def positionals(self):
        """Return positional arguments in order, excluding option values."""
        return list(self._positionals)

    def to_config(self):
        return {'argv': list(self.argv), 'flags': list(self.flags)}

    @input
    def get(self, *names, default=None):
        """Query aliases, or a single positional index (negative indexes work)."""
        if len(names) == 1 and type(names[0]) is int:
            try:
                return self._positionals[names[0]]
            except IndexError:
                return default
        if not names or not all(isinstance(name, str) and self._is_option(name)
                                and name != '--' and '=' not in name for name in names):
            raise ValueError('Supply option aliases or one positional index')
        for name, value in reversed(self._options):
            if name in names:
                return value
        return default
