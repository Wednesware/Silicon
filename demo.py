"""Read top to bottom: commented Silicon examples, then a complete Snake game."""
# python demo.py                 Run the examples, then open Snake.
# python demo.py --tour          Run only the headless examples.
# python demo.py --reference     Print the example source code.
# python demo.py --snake         Open only Snake (App + Sulfur + Fluorine).
# python demo.py --seed 7 --save snake_save.json
#
# Core examples: Python 3.11+, standard library only.
# Desktop: Python 3.12+, n2 get fluorine, n2 get sulfur;
# also install wwn, pywebview, PySide6, qtpy and use a desktop session.
# Optional examples below are real functions; call them explicitly when their
# backend/files are available. Importing this file does not open or save anything.
import asyncio
import tempfile
import time
from functools import partial
from pathlib import Path

from silicon import (
    App, CharacterSelection, Collision2D, CommandOptions, Component, Effects,
    Event, Entity, Effect, FrontEnd, Game, GameControl, Gravity, GridMovement, Health, InputMap,
    Inventory, Lifetime, Multiplayer, Randomizer, Score, Session, ShellInput,
    SoundEffects, SoundPlayer, Stage2D, StageRenderer, State, StateMachine, Timer, Traits,
    Transform2D, TurnManager, Velocity, component, input, load_bundle, output,
    register, register_factory, save_bundle, update,
)


# 1. Custom components: state, configuration, inputs, outputs, lifecycle, updates.
# Stable registrations must be imported before loading saves. version is metadata;
# migrations are your responsibility. Keep saved state/config JSON-compatible.
@register('demo.Probe')
class Probe(Component):
    """A generic signal sink; JSON-friendly recorded arguments survive saves."""
    records = State([], scope='game')

    @input
    def record(self, *args, **kwargs):
        self.records = [*self.records, [list(args), kwargs]]


@register('demo.Counter', version=1)
class Counter(Component):
    """Custom config, shared state, isolated state and all lifecycle hooks."""
    total = State(0)  # Shared when THIS object is attached to several games.
    local = State(0, scope='game')
    elapsed = State(0.0, scope='game')

    def __init__(self, label='counter'):
        super().__init__()
        self.label = label
        self.lifecycle = []  # Runtime diagnostic; deliberately not serialized.

    def to_config(self):
        # Plain attributes are saved only when included in the config.
        return {'label': self.label}

    @classmethod
    def from_config(cls, config):
        return cls(**config)

    def on_attach(self, game): self.lifecycle.append(('attach', game.name))
    def on_detach(self, game): self.lifecycle.append(('detach', game.name))
    def on_start(self, game): self.lifecycle.append(('start', game.name))
    def on_pause(self, game): self.lifecycle.append(('pause', game.name))
    def on_resume(self, game): self.lifecycle.append(('resume', game.name))
    def on_stop(self, game): self.lifecycle.append(('stop', game.name))

    @input
    def add(self, amount: int):
        self.total += amount
        self.local += amount
        self.out.changed(self.local)

    @output
    def changed(self, value: int): pass

    # One update method per component. Use @update() for one call per Game.step.
    @update(rate=10)
    def advance(self, dt):
        self.elapsed += dt


@component
def doubled(value: int):
    # Function components expose ins.value(value) and out.result(value).
    return value * 2


@component
async def async_doubled(value: int):
    await asyncio.sleep(0)
    return value * 2


# @component normally registers with the function's module name. Explicit stable
# registrations keep these two usable both as __main__ and as imported demo.
register('demo.Doubled')(doubled)
register('demo.AsyncDoubled')(async_doubled)


# 2. Games, binding, signal chains, fan-out, lifecycle and change notifications.
def core_example():
    game = Game('Workshop', tick_rate=60, seed=7)
    counter = game.add(Counter('workshop'), id='counter')
    game.add(Probe(), id='probe')
    game.add(doubled(), id='double')

    # Bind through a game, especially when one component belongs to many games.
    assert game.get('counter') is counter        # Raw component.
    assert game[counter].state.local == 0       # Game-bound State access.
    game['counter'].out.changed >> game['double'].ins.value
    game['double'].out.result >> game['probe'].ins.record
    game.connect(game['counter'].out.changed, game['probe'].ins.record)  # Fan-out.

    notifications = []
    unsubscribe = game.changed.connect(lambda: notifications.append(game.time))
    game.start()                                # Calls on_start(game).
    with game.batch():                          # One notification for both inputs.
        game['counter'].ins.add(3)              # changed(3) -> result(6).
        game[counter].in_.add(1)                # in_ is an alias for ins.
    print('Signal payloads:', game['probe'].state.records)
    print('Batch notification count (start + batch):', len(notifications))
    print('Shared / local state:', game[counter].state.total, game[counter].state.local)
    # State assignment notifies; in-place list/dict edits alone do not.
    # Use inputs or Session.action/transaction when changing mutable state.
    game[counter].state.local = 10
    game.step(0.25)                             # Two fixed 0.1-second updates.
    game.pause()                               # Calls on_pause; step now does nothing.
    game.step(50.0)
    game.resume()                              # Calls on_resume.
    print('Fixed update elapsed:', game[counter].state.elapsed)
    game.disconnect(game['counter'].out.changed, game['probe'].ins.record)
    temporary, another = game.add(Score(), Inventory())  # IDs generated automatically.
    game.remove(temporary)                     # Takes the raw component, removes wires.
    game.remove(another)
    unsubscribe()                              # Runtime listeners aren't serialized.
    game.stop()                                # Calls on_stop, cancels pending tasks.
    game.remove(counter)                       # Calls on_detach.
    print('Custom lifecycle:', counter.lifecycle)

    event = Event()
    off = event.connect(lambda value: print('Runtime Event:', value))
    event.emit('hello')
    off()
    off()                                      # Unsubscribe is idempotent.


# 3. Grid coordinates, mapped input, walls and terminal rendering.
def grid_example():
    game = Game('Grid')
    game.add(Probe(), id='probe')
    game.add(Stage2D(width=6, height=4), id='stage')
    game.add(InputMap(), id='keys')              # Lowercase WASD and Arrow* by default.
    game.add(GridMovement(entity='hero', stage_id='stage'), id='movement')
    game.add(StageRenderer(stage_id='stage', empty='.', border=True,
                           clear=False, ansi=False), id='renderer')

    game['keys'].out.action >> game['movement'].ins.command   # action(name: str).
    game['keys'].out.unknown >> game['probe'].ins.record      # unknown(key: str).
    game['movement'].out.moved >> game['probe'].ins.record    # moved(entity, x, y).
    game['movement'].out.blocked >> game['probe'].ins.record  # blocked(entity, x, y).
    # Stage events feed renderer inputs; these mark changes but don't draw.
    game['stage'].out.placed >> game['renderer'].ins.placed   # placed(entity, x, y).
    game['stage'].out.moved >> game['renderer'].ins.moved     # moved(entity, x, y).
    game['stage'].out.removed >> game['renderer'].ins.removed # removed(entity).
    game['renderer'].out.changed >> game['probe'].ins.record # changed().
    game['renderer'].out.rendered >> game['probe'].ins.record # rendered(frame: str).
    game.start()
    game['stage'].ins.place('hero', 1, 1)
    game['stage'].ins.place('wall', 2, 1)         # Stage allows shared cells itself.
    game['movement'].ins.solid('wall')           # GridMovement enforces occupancy.
    assert not game['movement'].ins.command('right')  # Blocked: False, attempted (2, 1).
    game['keys'].ins.feed('w')                   # Mapped to command('up').
    game['movement'].ins.move(1, 0)              # RELATIVE grid offset.
    game['stage'].ins.move('hero', 4, 2)         # ABSOLUTE grid coordinates.
    assert not game['keys'].ins.feed('?')        # Unknown key -> False.
    game['renderer'].ins.set_glyph('hero', '@')  # One character per glyph.
    game['renderer'].ins.set_glyph('wall', '#')
    game['renderer'].ins.hide('wall')
    game['renderer'].ins.show('wall')
    game['stage'].ins.remove('wall')             # Missing entity removal is a no-op.
    print('Frame without printing from renderer:', game.get('renderer').frame(game))
    game['renderer'].ins.draw()                 # Prints and emits rendered(frame).
    # Clearing a real terminal requires BOTH clear=True and ansi=True.
    game.stop()


# 4. Timers, turn order, named traits/effects, choices, randomness and modes.
def rules_example():
    game = Game('Rules', seed=7)
    game.add(Probe(), id='probe')
    game.add(Timer(seconds=0.2, repeat=False), id='timer')
    game.add(TurnManager(players=['Ada', 'Lin']), id='turns')
    game.add(Traits(), id='traits')
    game.add(Effects(), id='effects')
    game.add(CharacterSelection(choices=['ranger', 'mage']), id='characters')
    game.add(Randomizer(), id='dice')
    game.add(StateMachine(initial='ready'), id='mode')
    game.add(GameControl(), id='control')

    game['timer'].out.tick >> game['probe'].ins.record          # tick(remaining: float).
    game['timer'].out.finished >> game['probe'].ins.record      # finished().
    game['turns'].out.turn_started >> game['probe'].ins.record  # turn_started(player: str).
    game['turns'].out.round_started >> game['probe'].ins.record # round_started(number: int).
    game['traits'].out.changed >> game['probe'].ins.record      # changed(name: str, value: float).
    game['effects'].out.applied >> game['probe'].ins.record     # applied(name: str).
    game['effects'].out.expired >> game['probe'].ins.record     # expired(name: str).
    game['characters'].out.selected >> game['probe'].ins.record # selected(player, character).
    game['dice'].out.rolled >> game['probe'].ins.record         # rolled(value: int).
    game['mode'].out.changed >> game['probe'].ins.record        # changed(state: str).
    # GameControl has no outputs; these inputs operate on the bound game.
    game.start()
    game['timer'].ins.reset()                   # Full duration, inactive.
    game['timer'].ins.start()
    game.step(0.1)
    game['timer'].ins.stop()                    # Retains remaining 0.1 seconds.
    game['timer'].ins.start()                   # Resumes; refills only if empty.
    game.step(0.1)                             # tick(0.0), then finished().
    # repeat=True refills once on expiry; timer overshoot is discarded.
    game['turns'].ins.begin()                   # Ada starts round 1.
    game['turns'].ins.advance()                 # Lin.
    game['turns'].ins.advance()                 # Round 2, then Ada.
    game['traits'].ins.set('speed', 2.0)         # Float annotations require float values.
    game['effects'].ins.apply('shield', 1.0)
    game['effects'].ins.advance()               # Turn-based: subtract one second.
    game['effects'].ins.apply('haste', 0.1)
    game.step(0.1)                             # Time-based: subtract dt automatically.
    # Pick one advancement scheme to avoid counting the same turn twice.
    game['characters'].ins.select('Ada', 'ranger')  # Unknown choice raises ValueError.
    game['dice'].ins.roll(6)                    # Emits a seeded 1..6; no return value.
    game['mode'].ins.transition('exploring')    # Any string allowed; rules are yours.
    game['control'].ins.pause()                 # Updates pause; inputs still work.
    game['mode'].ins.transition('menu')
    game['control'].ins.resume()
    print('Rule events:', game['probe'].state.records)
    game['control'].ins.stop()


# 5. Health, inventory and scoring: inputs, return values and all outputs.
def resources_example():
    game = Game('Resources')
    game.add(Probe(), id='probe')
    game.add(Health(), id='health')
    game.add(Inventory(), id='inventory')
    game.add(Score(), id='score')
    game['health'].out.changed >> game['probe'].ins.record     # changed(entity, value: float).
    game['health'].out.died >> game['probe'].ins.record        # died(entity: str).
    game['inventory'].out.changed >> game['probe'].ins.record  # changed(item, count: int).
    game['inventory'].out.missing >> game['probe'].ins.record  # missing(item: str).
    game['score'].out.changed >> game['probe'].ins.record      # changed(value: int).
    game.start()
    game['health'].ins.add('hero', maximum=3)     # Starts full.
    game['health'].ins.damage('hero', amount=5)  # Clamps to zero; died fires once.
    game['health'].ins.damage('hero')            # Default amount=1; no second death.
    game['health'].ins.heal('hero', amount=2)    # Can revive; clamps at maximum.
    game['inventory'].ins.add('key', count=2)    # Counts must be positive integers.
    assert game['inventory'].ins.take('key')    # Default count=1.
    assert not game['inventory'].ins.take('key', count=2)  # Insufficient: unchanged.
    game['score'].ins.add(10)
    game['score'].ins.add(-2)                   # Negative score adjustments allowed.
    game['score'].ins.reset()
    print('Resource events:', game['probe'].state.records)
    game.stop()


# 6. Continuous movement and physics: positive y points downward.
def physics_tour():
    game = Game('Physics')
    game.add(Transform2D(), id='transform')
    # Insertion order matters: gravity changes velocity before integration.
    game.add(Gravity(acceleration=10.0, velocity_id='velocity', terminal_speed=20), id='gravity')
    game.add(Velocity(transform_id='transform'), id='velocity')
    game.add(Collision2D(transform_id='transform'), id='collision')
    game.add(Lifetime(), id='lifetime')
    game.add(Probe(), id='probe')
    game['transform'].out.moved >> game['probe'].ins.record   # moved(entity, x: float, y: float).
    game['transform'].out.removed >> game['probe'].ins.record # removed(entity: str).
    game['collision'].out.entered >> game['probe'].ins.record # entered(first, second).
    game['collision'].out.exited >> game['probe'].ins.record  # exited(first, second).
    # expired(entity) doesn't delete anything itself; fan out to cleanup inputs.
    game['lifetime'].out.expired >> game['transform'].ins.remove
    game['lifetime'].out.expired >> game['velocity'].ins.stop
    game['lifetime'].out.expired >> game['gravity'].ins.remove
    game['lifetime'].out.expired >> game['collision'].ins.remove
    # Velocity, Gravity and Lifetime have no other outputs.
    game.start()
    game['transform'].ins.place('ball', 0, 0)     # Also emits moved on first placement.
    game['transform'].ins.place('target', 0.5, 0)
    game['collision'].ins.add('ball')            # Default AABB width=1, height=1.
    game['collision'].ins.add('target', width=2, height=2)
    game['velocity'].ins.set('ball', x=1, y=0)   # Velocity in units/second.
    game['velocity'].ins.accelerate('ball', x=1, y=0)
    game['gravity'].ins.add('ball')
    game['lifetime'].ins.add('ball', seconds=0.3)
    game['lifetime'].ins.add('cancelled', seconds=5)
    game['lifetime'].ins.remove('cancelled')     # Cancel a countdown.
    game.step(0.1)                              # Overlap starts -> entered.
    game['transform'].ins.move('target', dx=10, dy=0)  # RELATIVE float offsets.
    game.step(0.1)                              # Overlap ends -> exited.
    print('Physics position after 0.2s:', game['transform'].state.positions['ball'])
    game.step(0.11)                             # Lifetime triggers all four cleanups.
    print('Lifetime removed ball:', 'ball' not in game['transform'].state.positions)
    # Detection only: edges touching aren't overlap; no response or swept tests.
    # Use small steps for fast objects. Gravity clamps vertical speed to +/- limit.
    game.stop()


# 7. Command-line parsing, scripted shell input and runtime frontend attachment.
def io_example():
    game = Game('IO')
    game.add(Probe(), id='probe')
    game.add(CommandOptions(['level.json', '--debug', '-p', '8000', '--port=9000',
                             '--', '-literal'], flags=['--debug']), id='options')
    # Omit argv to capture sys.argv[1:]. No output slots; values stay strings.
    assert game['options'].ins.get('--port', '-p') == '9000'  # Last alias wins.
    assert game['options'].ins.get('--debug') is True
    assert game['options'].ins.get(0) == 'level.json'
    assert game['options'].ins.get(-1) == '-literal'          # After -- is positional.
    assert game['options'].ins.get('--missing', default=42) == 42
    print('Positionals:', game.get('options').positionals)

    game.add(ShellInput(prompt='Move: ', options=['w'], iodine=False), id='shell')
    game['shell'].out.submitted >> game['probe'].ins.record  # submitted(value: str).
    game['shell'].out.invalid >> game['probe'].ins.record    # invalid(value: str).
    game['shell'].out.cancelled >> game['probe'].ins.record  # cancelled().
    assert game['shell'].ins.feed('w')           # Scripted, never blocks.
    assert not game['shell'].ins.feed('?')
    # Blocking read() and optional Iodine widgets: see shell_example below.

    game.add(FrontEnd(), id='frontend')
    game['frontend'].out.attached >> game['probe'].ins.record # attached().
    game['frontend'].out.selected >> game['probe'].ins.record # selected(name: str).
    pages = {'workshop': object()}              # Real application: Fluorine Pages.
    game['frontend'].ins.attach(pages)
    game['frontend'].ins.select('workshop')
    assert game.get('frontend').page(game) is pages['workshop']
    # A directly attached Page can also be returned without select().
    # FrontEnd stores no page in saves: reattach manually, or use Session.mount.
    game.stop()


# 8. Async input dispatch and an asyncio-driven Game loop.
def async_example():
    game = Game('Async inputs')
    game.add(async_doubled(), id='double')
    game.add(Probe(), id='probe')
    game['double'].out.result >> game['probe'].ins.record
    game['double'].ins.value(4)                  # No event loop: completes immediately.

    async def run():
        task = game['double'].ins.value(5)       # Running loop: returns a Task.
        await task
        loop_game = Game('Async loop', tick_rate=1000)
        loop_game.add(Timer(0.001), id='timer')
        loop_game.add(GameControl(), id='control')
        loop_game['timer'].out.finished >> loop_game['control'].ins.stop
        loop_game['timer'].ins.start()
        await loop_game.run(fps=1000)           # Starts game, steps wall time until stop.
        print('Async run stopped via Timer -> GameControl:', not loop_game.running)

    asyncio.run(run())
    print('Async results:', game['probe'].state.records)
    # Session.action must stay synchronous. Shared component active context is
    # not task-local; avoid concurrent async calls on the same shared object.


# 9. JSON saves, snapshots, custom factories and shared-component bundles.
def persistence_example():
    with tempfile.TemporaryDirectory(prefix='silicon-demo-') as folder:
        game = Game('Saved game', seed=7)
        game.add(Counter('saved counter'), id='counter')
        game.add(Probe(), id='probe')
        game['counter'].out.changed >> game['probe'].ins.record
        game.start()
        game['counter'].ins.add(3)
        path = Path(folder) / 'game.json'
        game.save(path)                         # Config, State, wires, time, flags, RNG.
        restored = Game.load(path)
        print('Save/load RNG continuation:', restored.random.random() == game.random.random())
        print('Save/load preserves connections:', restored.connections == game.connections)
        clone = Game()
        clone.restore(game.snapshot())          # Replaces components on this Game.
        # Factory overrides reconstruction and receives a config dictionary.
        register_factory('demo.Counter', lambda config: Counter(**config))

        shared = Counter('shared object')
        first, second = Game('First'), Game('Second')
        first.add(shared, id='counter')
        second.add(shared, id='counter')
        first[shared].ins.add(2)
        second[shared].ins.add(5)
        assert first[shared].state.total == second[shared].state.total == 7
        assert first[shared].state.local == 2
        assert second[shared].state.local == 5
        bundle = Path(folder) / 'bundle.json'
        save_bundle([first, second], bundle)
        a, b = load_bundle(bundle)
        print('Bundle retains object identity:', a.get('counter') is b.get('counter'))
        for current in (game, restored, clone, first, second, a, b):
            current.stop()
    # Temporary files deleted. Windows, pages, listeners, tasks and fixed-step
    # accumulators are runtime objects; save your own movement phase in State.


# 10. Sessions: locked actions, rendering, replacement, mounting and cleanup.
class ExampleSession(Session):
    @Session.action
    def award(self, amount):
        self.send('score', 'add', amount)        # Always resolves the current game.
        self.message = 'One complete action.'   # Render once after both changes.


def session_example():
    def factory():
        game = Game('Session example')
        game.add(Score(), id='score')
        return game                            # Session starts it automatically.

    with tempfile.TemporaryDirectory(prefix='silicon-session-') as folder:
        with ExampleSession(factory, Path(folder) / 'session.json') as session:
            renders = []
            off = session.watch(lambda: renders.append(session.state('score').value))
            changed_off = session.changed.connect(lambda: None)  # changed().
            replace_off = session.game_changed.connect(          # (previous, new).
                lambda old, new: print('Session replacement:', old.name, '->', new.name))
            session.closed.connect(lambda: print('Session closed'))  # closed().
            # Use a real Page in a UI; a named collection works without Fluorine.
            page = object()
            session.mount({'demo': page}, 'demo')
            # For a real Fluorine Page: session.mount(page).
            session.award(10)
            with session.transaction():         # Manual alternative to @Session.action.
                session.state('score').value = 11
                session.state('score').value = 10
            session.step(0.1)
            assert session.save()               # Returns success; errors go to message.
            session.send('score', 'reset')
            assert session.load()               # Failed load would keep current game.
            print('Session restored score:', session.state('score').value)
            assert session.game.get('frontend').page(session.game) is page
            session.restart()                   # New factory game; same page reattached.
            # Don't retain bound state/components across load/restart.
            off()
            changed_off()
            replace_off()
        # Context exit calls close(), stops game, and emits closed().


# 11. Optional integrations: actual callable examples, excluded from --tour.
def sound_example(wav_path):
    # n2 get carbon; pass the path to an existing WAV file.
    game = Game('Sound')
    game.add(Probe(), id='probe')
    game.add(SoundEffects(sounds={'eat': str(wav_path)}, prevent_overlap=True), id='sound')
    game['sound'].out.played >> game['probe'].ins.record  # played(name: str), not completion.
    game.start()
    game['sound'].ins.play('eat')                # Nonblocking Carbon playback.
    game['sound'].ins.stop('eat')
    game.stop()                                # Also stops this adapter's active files.
    # Carbon stops by filename; another game using the same file may be affected.


def sound_player_example(wav_path):
    # n2 get carbon; accepts a filename or pathlib.Path to an existing WAV.
    game = Game('Sound player')
    game.add(SoundPlayer(prevent_overlap=True), id='audio')
    game.add(Probe(), id='probe')
    game['audio'].out.played >> game['probe'].ins.record
    game['audio'].out.stopped >> game['probe'].ins.record
    game.start()
    try:
        game['audio'].ins.play(wav_path)        # Nonblocking playback request.
        game['audio'].ins.stop(wav_path)
        game['audio'].ins.stop_all()            # Only paths requested by this player.
    finally:
        game.stop()                            # Also cleans up on failure.


def shell_example(iodine=False):
    # Plain stdin by default; n2 get iodine to pass iodine=True.
    game = Game('Shell')
    game.add(Probe(), id='probe')
    game.add(ShellInput(prompt='Choose: ', options=['left', 'right', 'quit'],
                       iodine=iodine), id='shell')
    game['shell'].out.submitted >> game['probe'].ins.record  # submitted(value).
    game['shell'].out.invalid >> game['probe'].ins.record    # invalid(value).
    game['shell'].out.cancelled >> game['probe'].ins.record  # cancelled().
    value = game['shell'].ins.read()             # BLOCKS; EOF/Ctrl+C -> None, cancelled().
    # With iodine=True: options selects a menu; options=None selects a text editor.
    # An invalid read still returns its text; feed's boolean is the validation result.
    print('Read:', value)
    game.stop()


def desktop_example():
    # n2 get fluorine; n2 get sulfur. Full game implementation follows below.
    with SnakeInterface() as session:
        session.game.add(Probe(), id='app_events')
        session['app'].out.opened >> session['app_events'].ins.record  # opened().
        session['app'].out.closed >> session['app_events'].ins.record  # closed().
        # create_snake_game added App(frontend_id='frontend', name=..., width=..., height=...).
        # SnakeInterface mounted a Fluorine Page on that FrontEnd.
        from silicon.integrations import dependency
        session.page.body(dependency('fluorine').Element(
            'button', 'Close window', onclick=session['app'].ins.close))  # close().
        session['app'].ins.open(dev=False)      # BLOCKS; closes -> stops owning game.
        # Keep open OUTSIDE Session.action/transaction so callbacks can acquire its lock.


def multiplayer_example():
    # n2 get beryllium; pip install -r requirements-multiplayer.txt.
    # SnakeInterface builds a Fluorine Page; no Sulfur window is opened here.
    with SnakeInterface() as session:
        session.game.add(Probe(), id='network_events')
        network = Multiplayer(port=8000, host='0.0.0.0', max_clients=8,
                              print_url=True).bind(session, session.page)
        session['multiplayer'].out.connected >> session['network_events'].ins.record    # (player).
        session['multiplayer'].out.disconnected >> session['network_events'].ins.record # (player).
        session['multiplayer'].out.command >> session['network_events'].ins.record      # (player, name).
        network.action('move', lambda player, key: session.command(key))
        # Browser: beryllium.emit('move', {key: 'w'}). The player ID is injected.
        print('Players:', network.players)      # Runtime mapping of trusted IDs to clients.
        network.refresh()                      # Also refreshed after each session action.
        try:
            network.run(admin=False, sulfur=False)  # BLOCKS until server exits.
        finally:
            network.close()                    # Detach routes/subscriptions; idempotent.
        # All clients share ONE authoritative game; host/binding survive replacements.
        # This is an adapter recipe; Snake's desktop clock assumes one viewing client.


def syntax_example():
    game = Game('Nested components', seed=7)
    game[Stage2D(5, 3)]
    game[Stage2D][Entity('Player'):'player,hero']
    game[Entity:'player'] = game[Stage2D][Entity:'player']
    game.start >> [
        game[Stage2D][Entity:'*'].spawn,
        lambda game: game[Entity:'player'][Effect('protection', 1, 2):'#'],
    ]
    game.start()
    print('Spawned:', game[Entity:'player'].spawned)
    print('Effect turns:', game[Entity:'player'][Effect:'#'].remaining_turns)
    game.stop()


# Each entry links a built-in to the actual source example covering its slots.
COMPONENT_EXAMPLES = {
    Entity: syntax_example, Effect: syntax_example,
    Stage2D: grid_example, InputMap: grid_example, GridMovement: grid_example,
    StageRenderer: grid_example, Timer: rules_example, TurnManager: rules_example,
    Traits: rules_example, Effects: rules_example, CharacterSelection: rules_example,
    Randomizer: rules_example, StateMachine: rules_example, GameControl: rules_example,
    Health: resources_example, Inventory: resources_example, Score: resources_example,
    Transform2D: physics_tour, Gravity: physics_tour, Velocity: physics_tour,
    Collision2D: physics_tour, Lifetime: physics_tour, CommandOptions: io_example,
    ShellInput: shell_example, FrontEnd: io_example, SoundEffects: sound_example,
    App: desktop_example, Multiplayer: multiplayer_example,
    SoundPlayer: sound_player_example,
}
TOUR_EXAMPLES = (syntax_example, core_example, grid_example, rules_example, resources_example,
                 physics_tour, io_example, async_example, persistence_example, session_example)


def reference():
    # --reference prints the same source you can read here, not generated API prose.
    print(Path(__file__).read_text(encoding='utf-8'), end='')


def run_tour():
    for example in TOUR_EXAMPLES:
        print(f'\n--- {example.__name__} ---')
        example()


# ---------------------------------------------------------------------------
# The final example: Snake. Rules know nothing about Fluorine or Sulfur. The
# same factory works headlessly in tests, or under another Session/host.
# ---------------------------------------------------------------------------
DIRECTIONS = {'up': (0, -1), 'down': (0, 1), 'left': (-1, 0), 'right': (1, 0)}


@register('demo.Snake', version=1)
class Snake(Component):
    """Inputs: reset(), turn(direction). Outputs: ate(amount), ended(state).

    Updates at 60 Hz; stored elapsed time drives a score-dependent movement
    interval. At most two legal turns queue; one is consumed per movement.
    body is head-first, food is a cell or [], heading is a direction string.
    Stage2D mirrors these cells for renderers. ended emits 'lost' or 'won'.
    """
    body = State([], scope='game')
    food = State([], scope='game')
    heading = State('right', scope='game')
    turns = State([], scope='game')
    elapsed = State(0.0, scope='game')
    reason = State('Press Start to play.', scope='game')

    @input
    def reset(self):
        game = self._active_game
        stage = game.get('stage')
        x, y = stage.width // 2, stage.height // 2
        self.body = [[x, y], [x - 1, y], [x - 2, y]]
        self.heading, self.turns, self.elapsed = 'right', [], 0.0
        self.reason = 'Press Start to play.'
        game['score'].ins.reset()
        game['mode'].ins.transition('ready')
        self.spawn_food()
        self.sync_stage()

    @input
    def turn(self, direction: str):
        game = self._active_game
        if (direction not in DIRECTIONS or game.paused
                or game['mode'].state.current != 'running' or len(self.turns) >= 2):
            return False
        previous = self.turns[-1] if self.turns else self.heading
        px, py = DIRECTIONS[previous]
        dx, dy = DIRECTIONS[direction]
        if direction == previous or (dx == -px and dy == -py):
            return False
        self.turns = [*self.turns, direction]
        return True

    @output
    def ate(self, amount: int): pass

    @output
    def ended(self, state: str): pass

    def spawn_food(self):
        stage = self._active_game.get('stage')
        occupied = {tuple(cell) for cell in self.body}
        free = [[x, y] for y in range(stage.height) for x in range(stage.width)
                if (x, y) not in occupied]
        self.food = self._active_game.random.choice(free) if free else []

    def sync_stage(self):
        stage = self._active_game['stage']
        entities = {f'snake-{i}': cell for i, cell in enumerate(self.body)}
        if self.food:
            entities['food'] = self.food
        for entity in list(stage.state.cells):
            if entity not in entities:
                stage.ins.remove(entity)
        for entity, (x, y) in entities.items():
            if stage.state.cells.get(entity) != [x, y]:
                stage.ins.place(entity, x, y)

    def interval(self):
        return max(0.065, 0.20 - self._active_game['score'].state.value * 0.0005)

    @update(rate=60)
    def advance(self, dt):
        game = self._active_game
        if game['mode'].state.current != 'running':
            return
        self.elapsed += dt
        while self.elapsed + 1e-10 >= self.interval():
            self.elapsed -= self.interval()
            if self.turns:
                self.heading, self.turns = self.turns[0], self.turns[1:]
            dx, dy = DIRECTIONS[self.heading]
            x, y = self.body[0]
            head = [x + dx, y + dy]
            eating = head == self.food
            stage = game.get('stage')
            # The old tail vacates this turn unless we grow; moving onto it is legal.
            occupied = self.body if eating else self.body[:-1]
            if not (0 <= head[0] < stage.width and 0 <= head[1] < stage.height):
                self.reason = 'You hit the wall. New game to try again.'
                self.out.ended('lost')
                return
            if head in occupied:
                self.reason = 'You ran into yourself. New game to try again.'
                self.out.ended('lost')
                return
            self.body = [head, *(self.body if eating else self.body[:-1])]
            if eating:
                self.out.ate(10)
                self.spawn_food()
                if not self.food:
                    self.reason = 'Every cell filled. You win!'
                    self.out.ended('won')
            self.sync_stage()
            if game['mode'].state.current != 'running':
                return


def create_snake_game(seed=None, width=18, height=14):
    """Fresh game, wired entirely with serializable components/connections."""
    if width < 4 or height < 2:
        raise ValueError('Snake needs a board at least 4 by 2')
    game = Game('Silicon Snake', seed=seed)
    for name, comp in [
        ('stage', Stage2D(width, height)), ('keys', InputMap()), ('score', Score()),
        ('mode', StateMachine('ready')), ('control', GameControl()),
        ('snake', Snake()), ('frontend', FrontEnd()),
        ('app', App(name='Silicon — Snake', width=900, height=850)),
    ]:
        game.add(comp, id=name)
    game['keys'].out.action >> game['snake'].ins.turn
    game['snake'].out.ate >> game['score'].ins.add
    game['snake'].out.ended >> game['mode'].ins.transition
    game['snake'].ins.reset()
    return game


class SnakeSession(Session):
    """Synchronous controller; methods always resolve the currently loaded game."""
    def __init__(self, save_path='snake_save.json', seed=None):
        super().__init__(lambda: create_snake_game(seed=seed), save_path)
        self.last_pulse = time.monotonic()
        self.game_changed.connect(self.replaced)

    def replaced(self, previous, current):
        self.last_pulse = time.monotonic()

    @Session.action
    def command(self, key):
        return self.send('keys', 'feed', key)

    @Session.action
    def toggle(self):
        mode = self.state('mode').current
        if mode in ('lost', 'won') or not self.game.running:
            self.restart()
            mode = 'ready'
        if mode == 'ready':
            self.send('mode', 'transition', 'running')
        elif self.game.paused:
            self.send('control', 'resume')
        else:
            self.send('control', 'pause')
        self.last_pulse = time.monotonic()
        self.message = ''

    @Session.action
    def pulse(self):
        now = time.monotonic()
        dt = min(0.25, max(0.0, now - self.last_pulse))
        self.last_pulse = now
        if self.game.running and not self.game.paused and self.state('mode').current == 'running':
            self.step(dt)

    @Session.action
    def load(self, path=None):
        # Pause a restored active game to give the player time to get ready.
        result = super().load(path)
        if result and self.state('mode').current == 'running':
            if not self.game.running:
                self.game.start()
            self.send('control', 'pause')
        self.last_pulse = time.monotonic()
        return result


SNAKE_CSS = '''
:root { color-scheme: dark; font-family: system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #0c1520; color: #e9f4ef; }
main { max-width: 700px; margin: auto; padding: 24px; }
h1 { font-size: 38px; margin: 4px 0 8px; }
.eyebrow { color: #a9e66f; letter-spacing: .16em; font-size: 12px; }
.hint { color: #b0bfc9; font-size: 14px; line-height: 1.5; }
#stats { font-variant-numeric: tabular-nums; font-weight: bold; }
.board { display: grid; grid-template-columns: repeat(18, 1fr); gap: 2px;
  padding: 8px; background: #243342; border-radius: 12px; }
.cell { aspect-ratio: 1; border-radius: 3px; background: #111e2a; }
.cell.body { background: #70bf66; }
.cell.head { background: #c0f589; box-shadow: inset 0 0 0 3px #88ce68; }
.cell.food { background: #ff886b; border-radius: 50%; transform: scale(.75); }
#status { min-height: 48px; line-height: 1.5; }
.controls, .actions { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin: 12px 0; }
button { font: inherit; border: 1px solid #56717c; border-radius: 8px;
  padding: 10px 18px; background: #21333d; color: #e9f4ef; cursor: pointer; touch-action: manipulation; }
button:hover { background: #304d56; } button:focus-visible { outline: 3px solid #c0f589; }
#toggle { background: #476d32; } #clock { display: none; }
'''

SNAKE_SCRIPT = '''
// Re-evaluating a page must leave only one listener and one clock.
window.siliconSnakeKeys?.abort();
clearInterval(window.siliconSnakeClock);
window.siliconSnakeKeys = new AbortController();
document.addEventListener('keydown', e => {
  if (e.altKey || e.ctrlKey || e.metaKey || e.repeat) return;
  if (['INPUT','TEXTAREA','SELECT'].includes(e.target?.tagName)) return;
  const key = {ArrowUp:'w', ArrowLeft:'a', ArrowDown:'s', ArrowRight:'d'}[e.key]
      || e.key.toLowerCase();
  const id = {w:'move-w', a:'move-a', s:'move-s', d:'move-d',
              ' ':'toggle', p:'toggle', r:'restart'}[key];
  if (id) { e.preventDefault(); document.getElementById(id)?.click(); }
}, {signal: window.siliconSnakeKeys.signal});
// Use Fluorine's generated callback bridge via an ordinary hidden button.
// Python owns time/rules. No background Python thread touches UI/game state.
window.siliconSnakeClock = setInterval(() => {
  if (!document.hidden) document.getElementById('clock')?.click();
}, 50);
'''


class SnakeInterface(SnakeSession):
    """Fluorine element tree; Silicon App supplies its Sulfur callback bridge."""
    def __init__(self, save_path='snake_save.json', seed=None):
        # Optional imports stay here: --tour and --reference work without them.
        from silicon.integrations import dependency
        fluorine = dependency('fluorine')
        super().__init__(save_path, seed)
        try:
            E = fluorine.Element
            self.page = fluorine.Page('snake')
            self.page.head(E('title', 'Silicon Snake'),
                           E('meta', name='viewport', content='width=device-width, initial-scale=1'))
            # RawHTML is only used for this static, developer-owned stylesheet.
            self.page.head(E('style', fluorine.RawHTML(SNAKE_CSS)))
            self.stats = E('p', id='stats')
            self.status = E('p', id='status', role='status', aria_live='polite')
            self.toggle_button = E('button', 'Start', id='toggle', onclick=self.toggle)
            self.cells = {(x, y): E('div', class_='cell', role='img',
                                    aria_label=f'{x}, {y}: empty')
                          for y in range(14) for x in range(18)}
            self.page.body(E('main',
                E('p', 'SILICON / SIGNAL-DRIVEN ARCADE', class_='eyebrow'),
                E('h1', 'Snake'),
                E('p', 'Eat coral fruit. Grow. Leave yourself a way out.', class_='hint'),
                self.stats,
                E('div', *self.cells.values(), class_='board', aria_label='18 by 14 Snake board'),
                self.status,
                E('div', *(E('button', label, id=f'move-{key}',
                             onclick=partial(self.command, key), aria_label=f'Turn {direction}')
                           for key, label, direction in [('w', '↑', 'up'), ('a', '←', 'left'),
                                                         ('s', '↓', 'down'), ('d', '→', 'right')]),
                  class_='controls'),
                E('div', self.toggle_button,
                  E('button', 'New game', id='restart', onclick=self.restart),
                  E('button', 'Save', onclick=self.save),
                  E('button', 'Load', onclick=self.load), class_='actions'),
                E('p', 'WASD / arrows • Space / P pause • R new game. '
                  '10 points per fruit; speed rises with score. Walls are solid. '
                  'Loaded games pause. Closing the window ends the session.', class_='hint'),
                E('button', 'Clock', id='clock', onclick=self.pulse, tabindex='-1', aria_hidden='true'),
            ))
            self.page.script(SNAKE_SCRIPT)
            self.mount(self.page)
            self._painted = {}
            self.watch(self.refresh)
        except Exception:
            self.close()
            raise

    def refresh(self):
        mode = self.state('mode').current
        paused = self.game.paused
        snake = self.state('snake')
        score = self.state('score').value
        stats = f'SCORE {score}    •    LENGTH {len(snake.body)}    •    SPEED {1 / max(0.065, 0.20 - score * 0.0005):.1f} cells/s'
        if self.stats.text != stats:
            self.stats.text = stats
        positions = {tuple(position): ('head' if entity == 'snake-0' else 'food'
                                      if entity == 'food' else 'body')
                     for entity, position in self.state('stage').cells.items()}
        for position, cell in self.cells.items():
            kind = positions.get(position, 'empty')
            if self._painted.get(position) != kind:
                cell.set(class_='cell' if kind == 'empty' else f'cell {kind}',
                         aria_label=f'{position[0]}, {position[1]}: {kind}')
                self._painted[position] = kind
        if mode in ('lost', 'won', 'ready'):
            status = snake.reason
        elif paused:
            status = 'Paused. Press Resume or Space to continue.'
        else:
            status = 'Keep moving. No reversing into your neck!'
        if self.message:
            status += ' ' + self.message
        if self.status.text != status:
            self.status.text = status
        label = ('Play again' if mode in ('lost', 'won') else 'Start' if mode == 'ready'
                 else 'Resume' if paused else 'Pause')
        if self.toggle_button.text != label:
            self.toggle_button.text = label


def main(argv=None):
    options = CommandOptions(argv, flags=['--tour', '--reference', '--snake', '--help', '-h', '--dev'])
    if options.get('--help', '-h', default=False):
        print('Usage: demo.py [--tour | --reference | --snake] [--seed INTEGER] [--save PATH] [--dev]')
        print('Default: run the commented examples, then open Snake. Read demo.py for the walkthrough.')
        return
    tour = bool(options.get('--tour', default=False))
    only_reference = bool(options.get('--reference', default=False))
    only_snake = bool(options.get('--snake', default=False))
    if tour:
        run_tour()
    if only_reference:
        if not tour:
            reference()
    if (tour or only_reference) and not only_snake:
        return
    if not (tour or only_reference or only_snake):
        run_tour()
    seed = options.get('--seed')
    try:
        if seed is not None:
            if not isinstance(seed, str):
                raise ValueError
            seed = int(seed)
    except ValueError:
        raise SystemExit('--seed requires an integer') from None
    save_path = options.get('--save', default='snake_save.json')
    if not isinstance(save_path, str):
        raise SystemExit('--save requires a path')
    try:
        with SnakeInterface(save_path, seed) as ui:
            # Do not hold the Session lock while the native window blocks.
            ui['app'].ins.open(dev=bool(options.get('--dev', default=False)))
    except ImportError as exc:
        raise SystemExit(f'Desktop dependencies unavailable: {exc}\n'
                         'See python demo.py --help; --tour works without a desktop.') from exc


if __name__ == '__main__':
    main()
