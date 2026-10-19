"""Silicon: modular signal-driven game framework (prototype 0.1). Python 3.11+."""
from __future__ import annotations
import asyncio
import copy
import importlib
import inspect
import json
import random
import time
import types
import typing
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from threading import RLock

from .syntax import Entry, Selection, TriggerCall, trigger, _component_context, _tokens

_REGISTRY = {}
_FACTORIES = {}


class Event:
    """A runtime-only subscription; connect() returns an unsubscribe function."""
    def __init__(self):
        self._listeners = []

    def connect(self, callback):
        if not callable(callback):
            raise TypeError('Expected callable')
        subscription = (object(), callback)
        self._listeners.append(subscription)
        def disconnect():
            if subscription in self._listeners:
                self._listeners.remove(subscription)
        return disconnect

    def emit(self, *args):
        for _, callback in tuple(self._listeners):
            callback(*args)


def _game_operation(method):
    @wraps(method)
    def operation(self, *args, **kwargs):
        with self.batch():
            result = method(self, *args, **kwargs)
            self._notify_changed()
            return result
    return operation

def register(name=None, version=1):
    def deco(cls):
        cls._silicon_type = name or f'{cls.__module__}.{cls.__qualname__}'
        cls._silicon_version = version
        _REGISTRY[cls._silicon_type] = cls
        return cls
    return deco

def register_factory(name, factory):
    _FACTORIES[name] = factory

def input(fn):
    fn._silicon_input = True
    return fn

def output(fn):
    fn._silicon_output = True
    return fn

def update(rate=None):
    def deco(fn):
        fn._silicon_update = rate or 0
        return fn
    return deco

class State:
    def __init__(self, default, scope='shared'):
        if scope not in ('shared', 'game'):
            raise ValueError('scope must be shared or game')
        self.default, self.scope = default, scope
    def __set_name__(self, owner, name):
        self.name = name
    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        if self.scope == 'game':
            game = obj._active_game
            if game is None:
                raise RuntimeError(f'{self.name} requires an active game context; use game[component].state.{self.name}')
            return obj._local_state.setdefault(game, {}).setdefault(self.name, copy.deepcopy(self.default))
        return obj._shared_state.setdefault(self.name, copy.deepcopy(self.default))
    def __set__(self, obj, value):
        if self.scope == 'game':
            game = obj._active_game
            if game is None:
                raise RuntimeError(f'{self.name} requires an active game context')
            obj._local_state.setdefault(game, {})[self.name] = value
        else:
            obj._shared_state[self.name] = value
        games = (game,) if self.scope == 'game' else tuple(obj._games)
        for attached in games:
            attached._notify_changed()

class Slot:
    def __init__(self, component, name, direction, game=None):
        self.component, self.name, self.direction, self.game = component, name, direction, game
    def __rshift__(self, other):
        if self.direction != 'out' or not isinstance(other, Slot) or other.direction != 'in':
            raise TypeError('Connect output >> input')
        games = set(self.component._games) & set(other.component._games)
        if self.game: games &= {self.game}
        if other.game: games &= {other.game}
        if len(games) != 1:
            raise ValueError('Ambiguous connection: bind slots through game[component]')
        game = next(iter(games))
        game.connect(self, other)
        return other
    def __call__(self, *args, **kwargs):
        game = self.game or self.component._active_game
        if game is None:
            if len(self.component._games) != 1:
                raise RuntimeError('Ambiguous signal: use game[component].in/out')
            game = next(iter(self.component._games))
        if self.direction == 'in':
            return game._invoke(self.component, self.name, args, kwargs)
        game._emit(self.component, self.name, args, kwargs)

class Namespace:
    def __init__(self, component, direction, game=None):
        self.component, self.direction, self.game = component, direction, game
    def __getattr__(self, name):
        if name not in self.component._slots[self.direction]:
            raise AttributeError(f'No {self.direction} slot {name}')
        return Slot(self.component, name, self.direction, self.game)

class Component:
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        register()(cls)
    def __init__(self, *args, **kwargs):
        self._games = set()
        self._active_game = None
        self._shared_state = {}
        self._local_state = {}
        self._slots = {'in': {}, 'out': {}}
        for cls in reversed(type(self).__mro__):
            for name, value in vars(cls).items():
                if getattr(value, '_silicon_input', False): self._slots['in'][name] = value
                if getattr(value, '_silicon_output', False): self._slots['out'][name] = value
        self._update_fn = next(((n, f._silicon_update) for n, f in inspect.getmembers(type(self), inspect.isfunction) if hasattr(f, '_silicon_update')), None)
        bound = inspect.signature(self.__component__).bind(*args, **kwargs)
        bound.apply_defaults()
        self._component_config = copy.deepcopy(dict(bound.arguments))
        self.__component__(*args, **kwargs)
    def __component__(self): pass
    @property
    def game(self):
        if self._active_game is not None:
            return self._active_game
        if len(self._games) != 1:
            raise RuntimeError('Use game[component] to bind a shared or unattached component')
        return next(iter(self._games))
    @property
    def parent(self): return self.game._locations[self][0]
    @property
    def ids(self): return self.game._locations[self][1]
    @property
    def id(self): return self.ids[0] if self.ids else type(self).__name__
    def __getitem__(self, key): return Selection(self.game, self)[key]
    def __setitem__(self, key, source): Selection(self.game, self)[key] = source
    def __delitem__(self, key): del Selection(self.game, self)[key]
    @property
    def out(self): return Namespace(self, 'out', self._active_game)
    @property
    def ins(self): return Namespace(self, 'in', self._active_game)
    def __getattr__(self, name):
        if name == 'in_': return self.ins
        raise AttributeError(name)
    def on_attach(self, game): pass
    def on_detach(self, game): pass
    def on_start(self, game): pass
    def on_pause(self, game): pass
    def on_resume(self, game): pass
    def on_stop(self, game): pass
    def to_config(self): return copy.deepcopy(self._component_config)
    @classmethod
    def from_config(cls, config): return cls(**config)

class BoundState:
    def __init__(self, comp, game): self.comp, self.game = comp, game
    def __getattr__(self, name):
        descriptor = getattr(type(self.comp), name, None)
        if not isinstance(descriptor, State): raise AttributeError(name)
        if descriptor.scope == 'game':
            return self.comp._local_state.setdefault(self.game, {}).setdefault(name, copy.deepcopy(descriptor.default))
        return self.comp._shared_state.setdefault(name, copy.deepcopy(descriptor.default))
    def __setattr__(self, name, value):
        if name in ('comp', 'game'): return object.__setattr__(self, name, value)
        descriptor = getattr(type(self.comp), name, None)
        if not isinstance(descriptor, State): raise AttributeError(name)
        if descriptor.scope == 'game': self.comp._local_state.setdefault(self.game, {})[name] = value
        else: self.comp._shared_state[name] = value
        games = (self.game,) if descriptor.scope == 'game' else tuple(self.comp._games)
        for game in games:
            game._notify_changed()

class BoundComponent:
    def __init__(self, component, game):
        object.__setattr__(self, 'component', component)
        object.__setattr__(self, 'game', game)
    @property
    def out(self): return Namespace(self.component, 'out', self.game)
    @property
    def ins(self): return Namespace(self.component, 'in', self.game)
    @property
    def in_(self): return self.ins
    @property
    def state(self): return BoundState(self.component, self.game)
    @property
    def parent(self):
        parent = self.game._locations[self.component][0]
        return self.game if parent is self.game else BoundComponent(parent, self.game)
    @property
    def ids(self): return self.game._locations[self.component][1]
    @property
    def id(self): return self.ids[0] if self.ids else type(self.component).__name__
    def __getitem__(self, key): return Selection(self.game, self.component)[key]
    def __setitem__(self, key, source): Selection(self.game, self.component)[key] = source
    def __delitem__(self, key): del Selection(self.game, self.component)[key]
    def __getattr__(self, name):
        descriptor = inspect.getattr_static(type(self.component), name, None)
        if isinstance(descriptor, trigger):
            return TriggerCall(Selection(self.game, self.component), name, descriptor)
        old = self.component._active_game
        self.component._active_game = self.game
        try:
            value = getattr(self.component, name)
        finally:
            self.component._active_game = old
        if callable(value):
            @wraps(value)
            def call(*args, **kwargs):
                previous = self.component._active_game
                self.component._active_game = self.game
                try:
                    return value(*args, **kwargs)
                finally:
                    self.component._active_game = previous
            return call
        return value
    def __setattr__(self, name, value):
        old = self.component._active_game
        self.component._active_game = self.game
        try:
            setattr(self.component, name, value)
        finally:
            self.component._active_game = old

@dataclass
class Connection:
    source: str
    output: str
    target: str
    input: str

class Game:
    def __init__(self, name='Game', seed=None, *, tick_rate=60):
        self.name, self.tick_rate, self.seed = name, tick_rate, seed
        self.random = random.Random(seed)
        self.components = {}
        self.connections = []
        self._tree = {}
        self._locations = {}
        self._trigger_rules = []
        self._trigger_queue = deque()
        self._trigger_dispatching = False
        self.running = False
        self.paused = False
        self.time = 0.0
        self._queue = deque()
        self._dispatching = False
        self._tasks = set()
        self._accumulator = {}
        self._max_signals = 10000
        self.changed = Event()
        self._change_depth = 0
        self._change_pending = False

    @contextmanager
    def batch(self):
        """Coalesce nested mutations and signal dispatch into one changed event."""
        self._change_depth += 1
        try:
            yield self
        finally:
            self._change_depth -= 1
            if not self._change_depth and self._change_pending:
                self._change_pending = False
                self.changed.emit()

    def _notify_changed(self):
        self._change_pending = True
        if not self._change_depth:
            self._change_pending = False
            self.changed.emit()

    @_game_operation
    def add(self, *components, id=None, _defer_attach=False):
        if id is not None and len(components) != 1: raise ValueError('id requires one component')
        for comp in components:
            if not isinstance(comp, Component): raise TypeError('Expected Component')
            key = id or f'{type(comp).__name__.lower()}_{uuid.uuid4().hex[:8]}'
            if key in self.components: raise KeyError(f'Duplicate component ID: {key}')
            if comp in self.components.values(): raise ValueError('Component already attached to this game')
            self.components[key] = comp
            self._tree.setdefault(self, []).append(Entry(comp, (key,)))
            self._locations[comp] = (self, (key,), False)
            comp._games.add(self)
            comp._local_state.setdefault(self, {})
            if not _defer_attach:
                comp.on_attach(self)
        return components[0] if len(components) == 1 else components
    @_game_operation
    def remove(self, comp):
        key = self._id(comp)
        for child, location in tuple(self._locations.items()):
            if location[0] is comp:
                self.remove(child)
        for parent, entries in self._tree.items():
            entries[:] = [entry for entry in entries if entry.component is not comp]
        self._tree.pop(comp, None)
        self._locations.pop(comp, None)
        self.connections = [c for c in self.connections if c.source != key and c.target != key]
        del self.components[key]
        comp._games.discard(self)
        comp._local_state.pop(self, None)
        comp.on_detach(self)
    def _id(self, comp):
        for k, v in self.components.items():
            if v is comp: return k
        raise KeyError('Component not attached')
    @property
    def id(self): return 'Game'
    def __getitem__(self, comp_or_id):
        if isinstance(comp_or_id, str) and comp_or_id.endswith('?'):
            comp = self.components.get(comp_or_id[:-1])
            return None if comp is None else BoundComponent(comp, self)
        if isinstance(comp_or_id, (slice, type)):
            return Selection(self)[comp_or_id]
        if isinstance(comp_or_id, Component) and comp_or_id not in self._locations:
            return Selection(self)[comp_or_id]
        comp = self.components[comp_or_id] if isinstance(comp_or_id, str) else comp_or_id
        self._id(comp)
        return BoundComponent(comp, self)
    def __setitem__(self, key, source): Selection(self)[key] = source
    def __delitem__(self, key): del Selection(self)[key]
    @_game_operation
    def _insert(self, parent, comp, ids, *, link=False):
        entries = self._tree.setdefault(parent, [])
        typ = type(comp)
        singleton = ids is None
        used = {name for entry in entries if type(entry.component) is typ for name in entry.ids}
        names = []
        if singleton:
            if any(type(entry.component) is typ and entry.singleton for entry in entries):
                raise KeyError(f'{typ.__name__} singleton already exists')
        else:
            for token in _tokens(ids):
                if not token or '*' in token or '#-' in token:
                    raise ValueError('Creation requires explicit IDs or a # number template')
                if token.endswith('?'):
                    raise ValueError('The trailing ? suffix is reserved for optional lookups')
                if '#' in token:
                    if token.count('#') != 1 or not token.endswith('#'):
                        raise ValueError('A number template must end with one #')
                    prefix = token[:-1]
                    number = 0
                    while f'{prefix}{number}' in used | set(names):
                        number += 1
                    token = f'{prefix}{number}'
                if token in used:
                    raise KeyError(f'Duplicate {typ.__name__} ID: {token}')
                if token not in names:
                    names.append(token)
        # Reject cycles through both canonical children and shortcut links.
        pending, visited = [comp], set()
        while pending:
            descendant = pending.pop()
            if descendant is parent:
                raise ValueError('A component cannot be linked below itself')
            if descendant not in visited:
                visited.add(descendant)
                pending.extend(entry.component for entry in self._tree.get(descendant, ()))
        if not link:
            if comp in self._locations:
                raise ValueError('Component already attached; use assignment to link it')
            # The flat registry still drives lifecycle, updates and legacy signals.
            key = f'{typ.__name__.lower()}_{uuid.uuid4().hex}'
            self.components[key] = comp
            self._locations[comp] = (parent, tuple(names), singleton)
            comp._games.add(self)
            comp._local_state.setdefault(self, {})
        entries.append(Entry(comp, tuple(names), singleton))
        if not link:
            previous = comp._active_game
            comp._active_game = self
            try:
                comp.on_attach(self)
            except BaseException:
                self.remove(comp)
                raise
            finally:
                comp._active_game = previous
    def get(self, id): return self.components[id]
    def connect(self, source, target):
        if source.direction != 'out' or target.direction != 'in': raise TypeError('Expected output and input')
        src, dst = self._id(source.component), self._id(target.component)
        self._validate_connection(source, target)
        conn = Connection(src, source.name, dst, target.name)
        if conn not in self.connections: self.connections.append(conn)
    def disconnect(self, source, target):
        conn = Connection(self._id(source.component), source.name, self._id(target.component), target.name)
        self.connections.remove(conn)
    def _validate_connection(self, source, target):
        sfn = source.component._slots['out'][source.name]
        tfn = target.component._slots['in'][target.name]
        sh = _hints(sfn).get('return', inspect.Signature.empty)
        params = [p for p in inspect.signature(tfn).parameters.values() if p.name != 'self']
        if len(params) == 1 and sh not in (inspect.Signature.empty, None, type(None)):
            th = _hints(tfn).get(params[0].name, inspect.Signature.empty)
            if not _compatible(sh, th): raise TypeError(f'Incompatible signal: {sh} -> {th}')
    @_game_operation
    def _invoke(self, comp, name, args, kwargs):
        fn = comp._slots['in'][name]
        bound = getattr(comp, name)
        sig = inspect.signature(bound)
        sig.bind(*args, **kwargs)
        _validate_values(fn, args, kwargs)
        previous = comp._active_game
        comp._active_game = self
        try:
            result = bound(*args, **kwargs)
        finally:
            comp._active_game = previous
        if inspect.isawaitable(result):
            async def runner():
                old = comp._active_game
                comp._active_game = self
                try: return await result
                finally: comp._active_game = old
            try:
                task = asyncio.get_running_loop().create_task(runner())
            except RuntimeError:
                asyncio.run(runner())
                return None
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return task
        return result
    @_game_operation
    def _emit(self, comp, name, args, kwargs):
        fn = comp._slots['out'][name]
        _validate_values(fn, args, kwargs)
        source = self._id(comp)
        self._queue.append((source, name, args, kwargs))
        if self._dispatching: return
        self._dispatching = True
        try:
            count = 0
            while self._queue:
                count += 1
                if count > self._max_signals:
                    self._queue.clear()
                    raise RuntimeError('Signal limit exceeded (possible feedback loop)')
                src, outname, a, kw = self._queue.popleft()
                for conn in tuple(self.connections):
                    if conn.source == src and conn.output == outname:
                        self._invoke(self.components[conn.target], conn.input, a, kw)
        finally:
            self._dispatching = False
    @trigger
    @_game_operation
    def start(self):
        if self.running: return
        self.running, self.paused = True, False
        for c in tuple(self.components.values()): c.on_start(self)
    @trigger
    @_game_operation
    def pause(self):
        if self.running and not self.paused:
            self.paused = True
            for c in tuple(self.components.values()): c.on_pause(self)
    @trigger
    @_game_operation
    def resume(self):
        if self.running and self.paused:
            self.paused = False
            for c in tuple(self.components.values()): c.on_resume(self)
    @trigger
    @_game_operation
    def stop(self):
        if not self.running: return
        self.running = False
        for c in tuple(self.components.values()): c.on_stop(self)
        for task in tuple(self._tasks): task.cancel()
    @_game_operation
    def step(self, dt):
        if dt < 0: raise ValueError('dt must be nonnegative')
        if not self.running or self.paused: return
        self.time += dt
        for comp in tuple(self.components.values()):
            if not comp._update_fn: continue
            name, rate = comp._update_fn
            key = self._id(comp)
            if rate:
                interval = 1 / rate
                self._accumulator[key] = self._accumulator.get(key, 0) + dt
                iterations = 0
                while self._accumulator[key] + 1e-10 >= interval:
                    self._accumulator[key] -= interval
                    self._call_update(comp, name, interval)
                    iterations += 1
                    if iterations >= 1000: raise RuntimeError('Too many fixed updates')
            else: self._call_update(comp, name, dt)
    def _call_update(self, comp, name, dt):
        old = comp._active_game
        comp._active_game = self
        try:
            result = getattr(comp, name)(dt)
            if inspect.isawaitable(result):
                try: task = asyncio.get_running_loop().create_task(result)
                except RuntimeError: asyncio.run(result)
                else:
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
        finally: comp._active_game = old
    async def run(self, fps=None):
        self.start()
        fps = fps or self.tick_rate
        previous = time.monotonic()
        while self.running:
            await asyncio.sleep(1 / fps)
            now = time.monotonic()
            self.step(now - previous)
            previous = now
    def snapshot(self):
        records = []
        for key, comp in self.components.items():
            type_name = getattr(type(comp), '_silicon_type', f'{type(comp).__module__}.{type(comp).__qualname__}')
            records.append({'id': key, 'type': type_name, 'version': getattr(type(comp), '_silicon_version', 1),
                'config': comp.to_config(), 'shared': copy.deepcopy(comp._shared_state),
                'local': copy.deepcopy(comp._local_state.get(self, {}))})
        return {'schema': 1, 'name': self.name, 'tick_rate': self.tick_rate, 'seed': self.seed,
            'time': self.time, 'running': self.running, 'paused': self.paused,
            'rng': repr(self.random.getstate()), 'components': records,
            'connections': [vars(c).copy() for c in self.connections],
            'tree': self._snapshot_tree()}
    def _snapshot_tree(self):
        return [dict(parent=None if parent is self else self._id(parent),
                     component=self._id(entry.component), ids=list(entry.ids), singleton=entry.singleton,
                     canonical=self._locations[entry.component][0] is parent
                     and self._locations[entry.component][1] == entry.ids)
                for parent, entries in self._tree.items() for entry in entries]
    def _restore_tree(self, records):
        if records is None:
            return
        self._tree.clear()
        self._locations.clear()
        for record in records:
            parent = self if record['parent'] is None else self.components[record['parent']]
            comp = self.components[record['component']]
            entry = Entry(comp, tuple(record['ids']), record['singleton'])
            self._tree.setdefault(parent, []).append(entry)
            if record['canonical']:
                self._locations[comp] = (parent, entry.ids, entry.singleton)

    def _restore_attachments(self, records):
        for record in records:
            comp = self.components[record['id']]
            with _component_context(comp, self):
                comp.on_attach(self)
            # Attach hooks initialize defaults; saved state takes precedence.
            if 'shared' in record:
                comp._shared_state = copy.deepcopy(record['shared'])
            comp._local_state[self] = copy.deepcopy(record['local'])
    @_game_operation
    def restore(self, data):
        if data.get('schema') != 1: raise ValueError('Unsupported save schema')
        self.stop()
        for c in tuple(self.components.values()):
            if c in self._locations:
                self.remove(c)
        self.name, self.tick_rate, self.seed = data['name'], data['tick_rate'], data['seed']
        self.time = data['time']
        self.running, self.paused = False, False
        self._queue.clear()
        self._trigger_rules.clear()
        self._trigger_queue.clear()
        for item in data['components']:
            typ = item['type']
            if typ in _FACTORIES: comp = _FACTORIES[typ](item['config'])
            elif typ in _REGISTRY: comp = _REGISTRY[typ].from_config(item['config'])
            else: raise ValueError(f'Unregistered component type: {typ}')
            self.add(comp, id=item['id'], _defer_attach='tree' in data)
            comp._shared_state = copy.deepcopy(item['shared'])
            comp._local_state[self] = copy.deepcopy(item['local'])
        self._restore_tree(data.get('tree'))
        if 'tree' in data:
            self._restore_attachments(data['components'])
        for item in data['connections']:
            self.connect(self[item['source']].out.__getattr__(item['output']),
                         self[item['target']].ins.__getattr__(item['input']))
        if 'rng' in data:
            import ast
            self.random.setstate(ast.literal_eval(data['rng']))
        if data['running']:
            self.start()
            if data['paused']: self.pause()
    def save(self, path): Path(path).write_text(json.dumps(self.snapshot(), indent=2), encoding='utf-8')
    @classmethod
    def load(cls, path):
        game = cls()
        try:
            game.restore(json.loads(Path(path).read_text(encoding='utf-8')))
        except Exception:
            game.stop()
            raise
        return game

def _hints(fn):
    try: return typing.get_type_hints(fn)
    except (NameError, TypeError): return getattr(fn, '__annotations__', {})

def _compatible(out_type, in_type):
    if in_type in (inspect.Signature.empty, typing.Any) or out_type in (inspect.Signature.empty, typing.Any): return True
    if out_type == in_type: return True
    try: return issubclass(out_type, in_type)
    except TypeError: return True  # parameterized generics are checked at emission

def _validate_values(fn, args, kwargs):
    sig = inspect.signature(fn)
    bound = sig.bind(None, *args, **kwargs)
    hints = _hints(fn)
    for key, val in bound.arguments.items():
        if key == 'self': continue
        hint = hints.get(key, inspect.Signature.empty)
        if hint in (inspect.Signature.empty, typing.Any): continue
        origin = typing.get_origin(hint)
        check = origin or hint
        if isinstance(check, type) and not isinstance(val, check):
            raise TypeError(f'{key} expected {hint}, got {type(val).__name__}')

def component(fn):
    """Turn a single-input function into a component factory with .in_.value and .out.result."""
    params = list(inspect.signature(fn).parameters.values())
    if len(params) != 1: raise TypeError('Function components require exactly one argument')
    parameter = params[0]
    class Functional(Component):
        @input
        def value(self, value):
            result = fn(value)
            if inspect.isawaitable(result):
                async def emit_later(): self.out.result(await result)
                return emit_later()
            self.out.result(result)
        @output
        def result(self, value): pass
    Functional.__name__ = fn.__name__
    Functional.__qualname__ = fn.__name__
    Functional.__module__ = fn.__module__
    Functional.value.__annotations__ = {parameter.name: parameter.annotation}
    register(f'{fn.__module__}.{fn.__name__}')(Functional)
    return Functional

@register('silicon.Timer')
class Timer(Component):
    remaining = State(0.0, scope='game')
    active = State(False, scope='game')
    def __init__(self, seconds=60, repeat=False):
        super().__init__()
        self.seconds = float(seconds)
        self.repeat = bool(repeat)
    def to_config(self): return {'seconds': self.seconds, 'repeat': self.repeat}
    @input
    def start(self):
        if self.remaining <= 0: self.remaining = self.seconds
        self.active = True
    @input
    def stop(self): self.active = False
    @input
    def reset(self):
        self.remaining = self.seconds
        self.active = False
    @output
    def finished(self): pass
    @output
    def tick(self, remaining: float): pass
    @update()
    def advance(self, dt):
        if not self.active: return
        self.remaining = max(0.0, self.remaining - dt)
        self.out.tick(float(self.remaining))
        if self.remaining <= 0:
            self.out.finished()
            if self.repeat: self.remaining = self.seconds
            else: self.active = False

@register('silicon.TurnManager')
class TurnManager(Component):
    index = State(0, scope='game')
    round = State(1, scope='game')
    def __init__(self, players=None):
        super().__init__()
        self.players = list(players or [])
    def to_config(self): return {'players': self.players}
    @input
    def advance(self):
        if not self.players: return
        self.index += 1
        if self.index >= len(self.players):
            self.index = 0
            self.round += 1
            self.out.round_started(self.round)
        self.out.turn_started(self.players[self.index])
    @input
    def begin(self):
        if self.players: self.out.turn_started(self.players[self.index])
    @trigger
    def next_turn(self, entity=None):
        self.ins.advance()
    @output
    def turn_started(self, player: str): pass
    @output
    def round_started(self, number: int): pass

@register('silicon.Stage2D')
class Stage2D(Component):
    cells = State({}, scope='game')
    def __init__(self, width, height):
        super().__init__()
        self.width, self.height = int(width), int(height)
        if self.width <= 0 or self.height <= 0: raise ValueError('Invalid stage size')
    def to_config(self): return {'width': self.width, 'height': self.height}
    def _check(self, x, y):
        if not (0 <= x < self.width and 0 <= y < self.height): raise ValueError('Position outside stage')
    @input
    def place(self, entity: str, x: int, y: int):
        self._check(x, y)
        self.cells = {**self.cells, entity: [x, y]}
        self.out.placed(entity, x, y)
    @input
    def move(self, entity: str, x: int, y: int):
        self._check(x, y)
        if entity not in self.cells: raise KeyError(entity)
        self.cells = {**self.cells, entity: [x, y]}
        self.out.moved(entity, x, y)
    @input
    def remove(self, entity: str):
        if entity not in self.cells: return
        cells = dict(self.cells)
        del cells[entity]
        self.cells = cells
        self.out.removed(entity)
    @output
    def placed(self, entity: str, x: int, y: int): pass
    @output
    def moved(self, entity: str, x: int, y: int): pass
    @output
    def removed(self, entity: str): pass

@register('silicon.Entity')
class Entity(Component):
    """A named container with a spawn trigger; game rules choose its behavior."""
    spawned = State(False, scope='game')

    def __component__(self, name='Entity'):
        self.name = name

    @trigger
    def spawn(self):
        self.spawned = True


@register('silicon.Effect')
class Effect(Component):
    """A nested, turn-based effect. Connect proc to implement its game rules."""
    remaining_turns = State(0, scope='game')

    def __component__(self, name, value=1, turns=1):
        if turns < 0:
            raise ValueError('turns must be nonnegative')
        self.name, self.value, self.turns = name, value, turns

    def on_attach(self, game):
        self._local_state[game].setdefault('remaining_turns', self.turns)

    @trigger
    def proc(self):
        pass

    @trigger
    def reduce_remaining_turns(self, amount=1):
        if amount < 0:
            raise ValueError('amount must be nonnegative')
        self.remaining_turns = max(0, self.remaining_turns - amount)
        if self.remaining_turns == 0:
            self.game.remove(self)


@register('silicon.StageRenderer')
class StageRenderer(Component):
    """Character-cell terminal renderer for a Stage2D, without owning the stage.

    Connect stage.out.placed/moved/removed to matching renderer inputs.
    Rendering is explicit via render() or the draw input, making it usable in
    both turn-based and real-time games without unsolicited terminal output.
    """
    glyphs = State({}, scope='game')
    hidden = State([], scope='game')
    def __init__(self, stage_id='stage', empty='.', border=True, clear=False, ansi=False):
        super().__init__()
        if len(empty) != 1: raise ValueError('empty must be one character')
        self.stage_id = str(stage_id)
        self.empty = empty
        self.border = bool(border)
        self.clear = bool(clear)
        self.ansi = bool(ansi)
    def to_config(self):
        return dict(stage_id=self.stage_id, empty=self.empty, border=self.border, clear=self.clear, ansi=self.ansi)
    def _stage(self):
        game = self._active_game
        if game is None: raise RuntimeError('StageRenderer needs a game context')
        stage = game.get(self.stage_id)
        if not isinstance(stage, Stage2D): raise TypeError('stage_id must reference Stage2D')
        return stage
    @input
    def set_glyph(self, entity: str, glyph: str):
        if not glyph or len(glyph) != 1 or '\n' in glyph: raise ValueError('glyph must be one character')
        self.glyphs = {**self.glyphs, entity: glyph}
        self.out.changed()
    @input
    def hide(self, entity: str):
        self.hidden = list(dict.fromkeys([*self.hidden, entity]))
        self.out.changed()
    @input
    def show(self, entity: str):
        self.hidden = [name for name in self.hidden if name != entity]
        self.out.changed()
    @input
    def placed(self, entity: str, x: int, y: int): self.out.changed()
    @input
    def moved(self, entity: str, x: int, y: int): self.out.changed()
    @input
    def removed(self, entity: str): self.out.changed()
    def frame(self, game=None):
        game = game or self._active_game
        if game is None: raise RuntimeError('Use game[renderer].in_.draw() or renderer.frame(game)')
        stage = game.get(self.stage_id)
        if not isinstance(stage, Stage2D): raise TypeError('stage_id must reference Stage2D')
        cells = [[' ' if self.empty == ' ' else self.empty for _ in range(stage.width)] for _ in range(stage.height)]
        positions = game[stage].state.cells
        glyphs = game[self].state.glyphs
        hidden = set(game[self].state.hidden)
        for entity, pos in positions.items():
            if entity in hidden: continue
            x, y = pos
            if 0 <= x < stage.width and 0 <= y < stage.height:
                cells[y][x] = glyphs.get(entity, entity[:1] or '?')
        rows = [''.join(row) for row in cells]
        if self.border:
            edge = '+' + '-' * stage.width + '+'
            rows = [edge, *('|' + row + '|' for row in rows), edge]
        return '\n'.join(rows)
    @input
    def draw(self):
        frame = self.frame()
        if self.clear and self.ansi: print('\x1b[2J\x1b[H', end='')
        print(frame)
        self.out.rendered(frame)
    @output
    def changed(self): pass
    @output
    def rendered(self, frame: str): pass

@register('silicon.FrontEnd')
class FrontEnd(Component):
    """Optional front-end with Wednesware Fluorine; no rendering or web server included.

    Page/Site instances are external runtime objects and intentionally are not
    serialized. Attach them again after loading a saved game.
    """
    selected_page = State('', scope='game')
    def __init__(self, site=None):
        super().__init__()
        self.site = site
    def to_config(self): return {}
    @input
    def attach(self, site: object):
        self.site = site
        self.out.attached()
    @input
    def select(self, name: str):
        if self.site is None: raise RuntimeError('No Fluorine site attached')
        try:
            page = self.site[name]
        except (KeyError, TypeError, AttributeError):
            try: page = self.site / name
            except (TypeError, KeyError, AttributeError) as exc: raise KeyError(f'No page named {name!r}') from exc
        self.selected_page = name
        self.out.selected(name)
        return page
    def page(self, game=None):
        game = game or self._active_game
        if self.site is None: return None
        if game is None: raise RuntimeError('Supply game when accessing a shared FrontEnd component')
        name = game[self].state.selected_page
        if not name: return self.site
        try: return self.site[name]
        except (KeyError, TypeError, AttributeError): return self.site / name
    @output
    def attached(self): pass
    @output
    def selected(self, name: str): pass

@register('silicon.Traits')
class Traits(Component):
    values = State({}, scope='game')
    @input
    def set(self, name: str, value: float):
        self.values = {**self.values, name: value}
        self.out.changed(name, value)
    @output
    def changed(self, name: str, value: float): pass

@register('silicon.Effects')
class Effects(Component):
    effects = State({}, scope='game')
    @input
    def apply(self, name: str, duration: float):
        self.effects = {**self.effects, name: float(duration)}
        self.out.applied(name)
    @input
    def advance(self): self._advance(1.0)
    @update()
    def _update(self, dt): self._advance(dt)
    def _advance(self, dt):
        new = {k: v - dt for k, v in self.effects.items()}
        expired = [k for k, v in new.items() if v <= 0]
        self.effects = {k: v for k, v in new.items() if v > 0}
        for name in expired: self.out.expired(name)
    @output
    def applied(self, name: str): pass
    @output
    def expired(self, name: str): pass

@register('silicon.CharacterSelection')
class CharacterSelection(Component):
    selections = State({}, scope='game')
    def __init__(self, choices=None):
        super().__init__()
        self.choices = list(choices or [])
    def to_config(self): return {'choices': self.choices}
    @input
    def select(self, player: str, character: str):
        if character not in self.choices: raise ValueError('Unknown character')
        self.selections = {**self.selections, player: character}
        self.out.selected(player, character)
    @output
    def selected(self, player: str, character: str): pass

@register('silicon.Randomizer')
class Randomizer(Component):
    @input
    def roll(self, sides: int):
        if sides < 1: raise ValueError('sides must be positive')
        self.out.rolled(self._active_game.random.randint(1, sides))
    @output
    def rolled(self, value: int): pass

@register('silicon.StateMachine')
class StateMachine(Component):
    current = State('', scope='game')
    def __init__(self, initial=''): super().__init__(); self.initial = initial
    def to_config(self): return {'initial': self.initial}
    def on_attach(self, game):
        self._local_state[game].setdefault('current', self.initial)
    @input
    def transition(self, state: str):
        old = self.current
        self.current = state
        self.out.changed(state)
    @output
    def changed(self, state: str): pass

@register('silicon.GameControl')
class GameControl(Component):
    @input
    def stop(self): self._active_game.stop()
    @input
    def pause(self): self._active_game.pause()
    @input
    def resume(self): self._active_game.resume()


def save_bundle(games, path):
    games = list(games)
    ids = {}
    shared = {}
    snapshots = []
    for game in games:
        snap = game.snapshot()
        for record in snap['components']:
            comp = game.components[record['id']]
            ident = ids.setdefault(comp, f'component_{len(ids)}')
            shared[ident] = record['shared']
            record['shared_ref'] = ident
            del record['shared']
        snapshots.append(snap)
    Path(path).write_text(json.dumps({'bundle_schema': 1, 'shared': shared, 'games': snapshots}, indent=2), encoding='utf-8')

def load_bundle(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('bundle_schema') != 1: raise ValueError('Unsupported bundle')
    pool = {}
    games = []
    for snap in data['games']:
        game = Game(snap['name'], seed=snap['seed'], tick_rate=snap['tick_rate'])
        game.time = snap['time']
        for record in snap['components']:
            ref = record['shared_ref']
            if ref not in pool:
                typ = record['type']
                if typ in _FACTORIES: pool[ref] = _FACTORIES[typ](record['config'])
                elif typ in _REGISTRY: pool[ref] = _REGISTRY[typ].from_config(record['config'])
                else: raise ValueError(f'Unregistered component: {typ}')
                pool[ref]._shared_state = data['shared'][ref]
            comp = pool[ref]
            game.add(comp, id=record['id'], _defer_attach='tree' in snap)
            comp._local_state[game] = copy.deepcopy(record['local'])
        game._restore_tree(snap.get('tree'))
        if 'tree' in snap:
            game._restore_attachments(snap['components'])
        for c in snap['connections']:
            game.connect(getattr(game[c['source']].out, c['output']), getattr(game[c['target']].ins, c['input']))
        if 'rng' in snap:
            import ast
            game.random.setstate(ast.literal_eval(snap['rng']))
        if snap['running']:
            game.start()
            if snap['paused']: game.pause()
        games.append(game)
    return games


def _session_action(method):
    """Serialize a synchronous session operation and render its final state once."""
    @wraps(method)
    def action(self, *args, **kwargs):
        with self.transaction():
            return method(self, *args, **kwargs)
    return action


class Session:
    """Own a replaceable game and its runtime UI, independently of a UI library.

    Subclass for application actions, or compose with an existing controller.
    Use @Session.action for synchronous UI callbacks. Observers run once after
    each action, after its signals and status updates have completed.
    """
    action = staticmethod(_session_action)

    def __init__(self, factory, save_path='save.json'):
        if not callable(factory):
            raise TypeError('Expected a game factory')
        self.factory = factory
        self.save_path = Path(save_path)
        self.changed = Event()
        self.game_changed = Event()
        self.closed = Event()
        self._lock = RLock()
        self._depth = 0
        self._pending = False
        self._closed = False
        self._message = ''
        self._site = None
        self._page_name = None
        self.game = self._create_game()
        self._disconnect_game = self.game.changed.connect(self._notify_changed)

    def _create_game(self):
        game = self.factory()
        if not isinstance(game, Game):
            raise TypeError('Game factory must return a Game')
        if game is getattr(self, 'game', None):
            raise ValueError('Game factory must return a new game when restarting')
        try:
            game.start()
        except Exception:
            game.stop()
            raise
        return game

    @contextmanager
    def transaction(self):
        """Lock an action and defer observers until its complete game state is ready."""
        with self._lock:
            if self._closed:
                raise RuntimeError('Session is closed')
            self._depth += 1
            # An action may mutate a dictionary/list without a State assignment.
            self._pending = True
            try:
                with self.game.batch():
                    yield self
            finally:
                self._depth -= 1
                if not self._depth and self._pending:
                    self._pending = False
                    if not self._closed:
                        self.changed.emit()

    def _notify_changed(self):
        with self._lock:
            if self._closed:
                return
            if self._depth:
                self._pending = True
            else:
                self.changed.emit()

    @property
    def message(self):
        return self._message

    @message.setter
    def message(self, value):
        with self._lock:
            if self._message != value:
                self._message = value
                self._notify_changed()

    def watch(self, callback, *, immediate=True):
        """Subscribe a zero-argument renderer, optionally rendering immediately."""
        with self._lock:
            if self._closed:
                raise RuntimeError('Session is closed')
            disconnect = self.changed.connect(callback)
            if immediate:
                try:
                    callback()
                except Exception:
                    disconnect()
                    raise
            return disconnect

    def __getitem__(self, component):
        return self.game[component]

    def state(self, component):
        """Read or assign explicitly game-bound state in the current game."""
        return self[component].state

    @_session_action
    def send(self, component, name, *args, **kwargs):
        """Invoke an input on the current game, including after load or restart."""
        return getattr(self[component].ins, name)(*args, **kwargs)

    @_session_action
    def step(self, dt):
        self.game.step(dt)

    @_session_action
    def mount(self, site, name=None):
        """Keep a page or page collection attached across game replacements."""
        if name is None:
            name = getattr(site, 'name', None)
            if not isinstance(name, str):
                raise ValueError('Supply a page name when mounting a page collection')
            site = {name: site}
        # Validate before replacing the retained runtime attachment.
        site[name]
        self._attach_frontend(self.game, site, name)
        self._site, self._page_name = site, name

    def _attach_frontend(self, game, site, name):
        if 'frontend' not in game.components:
            game.add(FrontEnd(), id='frontend')
        elif not isinstance(game.get('frontend'), FrontEnd):
            raise TypeError('The frontend component must be a FrontEnd')
        game['frontend'].ins.attach(site)
        game['frontend'].ins.select(name)

    def _replace(self, candidate):
        if candidate is self.game:
            raise ValueError('Game factory must return a new game when restarting')
        self._prepare(candidate)
        self._adopt(candidate)

    def _prepare(self, candidate):
        try:
            if self._site is not None:
                self._attach_frontend(candidate, self._site, self._page_name)
        except Exception:
            candidate.stop()
            raise

    def _adopt(self, candidate):
        previous = self.game
        self._disconnect_game()
        self.game = candidate
        self._disconnect_game = candidate.changed.connect(self._notify_changed)
        previous.stop()
        self._notify_changed()
        self.game_changed.emit(previous, candidate)

    @_session_action
    def save(self, path=None):
        try:
            self.game.save(self.save_path if path is None else path)
        except OSError as exc:
            self.message = f'Could not save: {exc}'
            return False
        self.message = 'Game saved.'
        return True

    @_session_action
    def load(self, path=None):
        try:
            candidate = Game.load(self.save_path if path is None else path)
            self._prepare(candidate)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.message = f'Could not load: {exc}'
            return False
        self._adopt(candidate)
        self.message = 'Game restored.'
        return True

    @_session_action
    def restart(self):
        self._replace(self._create_game())
        self.message = 'A fresh game awaits.'

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._disconnect_game()
            try:
                self.game.stop()
            finally:
                self.closed.emit()

    def __enter__(self):
        if self._closed:
            raise RuntimeError('Session is closed')
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

__all__ = [
    'Game',
    'Session',
    'Event',
    'Component',
    'State',
    'input',
    'output',
    'update',
    'trigger',
    'component',
    'register',
    'register_factory',
    'save_bundle',
    'load_bundle',
    
    'Timer',
    'TurnManager',
    'Stage2D',
    'Entity',
    'Effect',
    'StageRenderer',
    'FrontEnd',
    'Traits',
    'Effects',
    'CharacterSelection',
    'Randomizer',
    'StateMachine',
    'GameControl',
]


from .components import (Transform2D, Velocity, Gravity, InputMap, GridMovement,
                         Collision2D, Health, Inventory, Score, Lifetime, CommandOptions)
from .integrations import App, Multiplayer, ShellInput, SoundEffects, SoundPlayer

__all__ += ['Transform2D', 'Velocity', 'Gravity', 'InputMap', 'GridMovement',
            'Collision2D', 'Health', 'Inventory', 'Score', 'Lifetime',
            'App', 'Multiplayer', 'ShellInput', 'SoundEffects', 'SoundPlayer', 'CommandOptions']
