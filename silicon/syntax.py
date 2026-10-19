"""Tree selectors and named-context triggers used by Silicon's public syntax."""
from __future__ import annotations

import copy
import inspect
import re
from contextlib import contextmanager
from dataclasses import dataclass
from functools import update_wrapper

from .utils import _DeferredAction


@dataclass
class Entry:
    component: object
    ids: tuple[str, ...]
    singleton: bool = False


def _core():
    from . import BoundComponent, Component
    return BoundComponent, Component


def _parts(key):
    _, Component = _core()
    if isinstance(key, slice):
        if key.step is not None:
            raise TypeError('Use [Component:ids], without a slice step')
        value, ids = key.start, key.stop
    else:
        value, ids = key, None
    typ = type(value) if isinstance(value, Component) else value
    if not isinstance(typ, type) or not issubclass(typ, Component):
        raise TypeError('Expected a component instance or component type')
    return value, typ, ids


def _tokens(ids):
    if isinstance(ids, (tuple, list)):
        return [str(item).strip() for item in ids]
    return [item.strip() for item in str(ids).split(',')]


def _lookup_ids(ids):
    tokens = _tokens(ids)
    optional = bool(tokens and tokens[-1].endswith('?'))
    if optional:
        tokens[-1] = tokens[-1][:-1]
    return tokens, optional


def _matching(entries, typ, ids):
    entries = [entry for entry in entries if type(entry.component) is typ]
    if ids is None:
        return [entry.component for entry in entries if entry.singleton]
    selected = []
    for token in _lookup_ids(ids)[0]:
        if token == '*':
            matches = entries
        elif '*' in token:
            pattern = re.compile('.*'.join(re.escape(part) for part in token.split('*')), re.DOTALL)
            matches = [entry for entry in entries if any(pattern.fullmatch(name) for name in entry.ids)]
        elif re.fullmatch(r'.*#(?:-\d+)?', token):
            prefix, _, offset = token.rpartition('#')
            numbered = [entry for entry in entries if any(
                name.startswith(prefix) and name[len(prefix):].isdigit() for name in entry.ids)]
            index = -1 + int(offset or 0)
            matches = numbered[index:index + 1] if index != -1 else numbered[-1:]
        else:
            matches = [entry for entry in entries if token in entry.ids]
        for entry in matches:
            if entry.component not in selected:
                selected.append(entry.component)
    return selected


class Selection:
    """A live, typed path. ID lookups require matches unless suffixed with ?."""
    def __init__(self, game, root=None, path=()):
        object.__setattr__(self, 'game', game)
        object.__setattr__(self, '_root', game if root is None else root)
        object.__setattr__(self, '_path', path)

    def _resolve(self, *, strict=True):
        current = [self._root]
        for typ, ids in self._path:
            children = []
            for parent in current:
                for comp in _matching(self.game._tree.get(parent, ()), typ, ids):
                    if comp not in children:
                        children.append(comp)
            current = children
            if not current and ids is not None and strict and not _lookup_ids(ids)[1]:
                raise LookupError(f'No {typ.__name__} matches ID selector {ids!r}')
        return current

    @property
    def component(self):
        components = self._resolve()
        if len(components) != 1:
            raise LookupError(f'Expected one component, selected {len(components)}')
        return components[0]

    def __getitem__(self, key):
        value, typ, ids = _parts(key)
        _, Component = _core()
        if isinstance(value, Component):
            parents = self._resolve()
            components = [value, *(_clone(value) for _ in parents[1:])]
            for parent, comp in zip(parents, components):
                self.game._insert(parent, comp, ids)
        selection = Selection(self.game, self._root, (*self._path, (typ, ids)))
        if ids is not None and not selection._resolve() and _lookup_ids(ids)[1]:
            return None
        return selection

    def __setitem__(self, key, source):
        value, typ, ids = _parts(key)
        if value is not typ:
            raise TypeError('Link with [Component:ids] = source')
        BoundComponent, _ = _core()
        if not isinstance(source, (Selection, BoundComponent)) or source.game is not self.game:
            raise ValueError('Links must reference one component in the same game')
        comp = source.component
        if type(comp) is not typ:
            raise TypeError('A link must keep the component type')
        for parent in self._resolve():
            self.game._insert(parent, comp, ids, link=True)

    def __delitem__(self, key):
        selection = self[key]
        if selection is None:
            return
        for comp in selection._resolve():
            self.game.remove(comp)

    def __getattr__(self, name):
        typ = self._path[-1][0] if self._path else type(self._root)
        descriptor = inspect.getattr_static(typ, name, None)
        if isinstance(descriptor, trigger):
            return TriggerCall(self, name, descriptor)
        BoundComponent, _ = _core()
        return getattr(BoundComponent(self.component, self.game), name)

    def __setattr__(self, name, value):
        BoundComponent, _ = _core()
        setattr(BoundComponent(self.component, self.game), name, value)

    def __iter__(self):
        BoundComponent, _ = _core()
        return iter([BoundComponent(comp, self.game) for comp in self._resolve()])

    def __len__(self):
        return len(self._resolve())

    def __bool__(self):
        return bool(self._resolve())

    def __repr__(self):
        return f'<Selection {self._resolve()!r}>'


def _clone(component):
    """Clone an unattached template without copying a game's locks or runtime state."""
    clone = object.__new__(type(component))
    clone._games = set()
    clone._active_game = None
    clone._local_state = {}
    for name, value in vars(component).items():
        if name not in {'_games', '_active_game', '_local_state'}:
            setattr(clone, name, copy.deepcopy(value))
    return clone


class trigger:
    """A synchronous method that can also connect to callbacks with >>."""
    def __init__(self, function):
        if inspect.iscoroutinefunction(function):
            raise TypeError('@trigger methods must be synchronous')
        self.function = function
        update_wrapper(self, function)

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return TriggerCall(instance, self.__name__, self)


@contextmanager
def _component_context(component, game):
    previous = []
    current = component
    while current is not game:
        previous.append((current, current._active_game))
        current._active_game = game
        location = game._locations.get(current)
        if location is None:
            break
        current = location[0]
    try:
        yield
    finally:
        for comp, active_game in reversed(previous):
            comp._active_game = active_game


class TriggerCall:
    def __init__(self, source, name, descriptor):
        self.source, self.name, self.descriptor = source, name, descriptor

    @property
    def game(self):
        if isinstance(self.source, Selection):
            return self.source.game
        if hasattr(self.source, '_tree'):
            return self.source
        return self.source.game

    def _sources(self, *, strict=True):
        return self.source._resolve(strict=strict) if isinstance(self.source, Selection) else [self.source]

    def __rshift__(self, targets):
        self._sources()
        targets = targets if isinstance(targets, (list, tuple)) else [targets]
        if any(not callable(target) for target in targets):
            raise TypeError('Trigger targets must be callables; defer creation with a lambda')
        if any(isinstance(target, TriggerCall) and target.game is not self.game for target in targets):
            raise ValueError('Triggers cannot connect across games')
        self.game._trigger_rules.append((self, tuple(targets)))
        return self

    def __call__(self, *args, **kwargs):
        game = self.game
        results = []
        with game.batch():
            jobs = [(self, comp, args, kwargs, {}, results) for comp in self._sources()]
            if game._trigger_dispatching:
                game._trigger_queue.extendleft(reversed(jobs))
            else:
                game._trigger_queue.extend(jobs)
            self._drain()
        return results[0] if len(results) == 1 else results or None

    def _drain(self):
        game = self.game
        if game._trigger_dispatching:
            return
        game._trigger_dispatching = True
        try:
            count = 0
            while game._trigger_queue:
                count += 1
                if count > game._max_signals:
                    raise RuntimeError('Trigger limit exceeded (possible feedback loop)')
                call, comp, args, kwargs, context, results = game._trigger_queue.popleft()
                if call is None:
                    comp()
                    continue
                if comp is not game and comp not in game._locations:
                    continue
                if comp is game:
                    inactive = {
                        'start': game.running,
                        'pause': not game.running or game.paused,
                        'resume': not game.running or not game.paused,
                        'stop': not game.running,
                    }
                    if inactive.get(call.name, False):
                        continue
                context = dict(context)
                context['game'] = game
                if comp is not game:
                    lineage, ancestors = comp, {}
                    while lineage is not game:
                        ancestors.setdefault(_type_parameter(type(lineage)), lineage)
                        lineage = game._locations[lineage][0]
                    context.update(ancestors)
                    context['component'] = comp
                    context['parent'] = game._locations[comp][0]
                bound = call.descriptor.function.__get__(comp, type(comp))
                with _component_context(comp, game):
                    result, arguments = _invoke_named(bound, args, kwargs, context, details=True)
                    context.update(arguments)
                    results.append(result)
                    callbacks = []
                    for rule, targets in tuple(game._trigger_rules):
                        if rule.name == call.name and comp in rule._sources(strict=False):
                            for target in targets:
                                callbacks.append((None, _callback(target, comp, game, context), (), {}, context, []))
                    game._trigger_queue.extendleft(reversed(callbacks))
                game._notify_changed()
        except BaseException:
            game._trigger_queue.clear()
            raise
        finally:
            game._trigger_dispatching = False


def _type_parameter(typ):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', typ.__name__).lower()


def _callback(target, emitter, game, context):
    def run():
        if isinstance(target, TriggerCall):
            jobs = [(target, comp, (), {}, context, []) for comp in target._sources()]
            game._trigger_queue.extendleft(reversed(jobs))
            return
        with _component_context(emitter, game):
            return _invoke_named(target, (), {}, context)
    return run


def _invoke_named(function, args, kwargs, context, *, details=False):
    signature = inspect.signature(function)
    bound = signature.bind_partial(*args, **kwargs)
    for name, parameter in signature.parameters.items():
        if name not in bound.arguments and name in context and parameter.kind not in (
                inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            bound.arguments[name] = context[name]
    signature.bind(*bound.args, **bound.kwargs)
    result = function(*bound.args, **bound.kwargs)
    if isinstance(result, _DeferredAction):
        name = getattr(result.function, '__name__', type(result.function).__name__)
        raise TypeError(
            f'Trigger handler returned an unexecuted deferred action from {name}(). '
            f'Connect {name}(...) directly with >>, or call {name}(...)() inside the handler.'
        )
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise TypeError('Trigger callbacks must be synchronous')
    return (result, bound.arguments) if details else result
