[![Wednesware](https://raw.githubusercontent.com/Wednesware/Document2.0/main/wednesware.png)](https://wednesware.org)

# Silicon

Silicon is a component-based game framework for Python 3.11+. Build a tree of components, select them by type and ID, and connect triggers with `>>`.

## Installation

> `n2 get silicon`

## Dependencies

- Nitrogen 26.66+ (`pip install wwn`)
- Other dependencies as required by optional integrations:
  - [Fluorine](https://github.com/Wednesware/Fluorine)
  - [Sulfur](https://github.com/Wednesware/Sulfur)
  - [Beryllium](https://github.com/Wednesware/Beryllium)
  - [Carbon](https://github.com/Wednesware/Carbon)
  - [Iodine](https://github.com/Wednesware/Iodine)

## Quick start

### Component tree and triggers

```python
from silicon import Game, Stage2D, Entity

game = Game('SnakeGame', seed=7)
game[Stage2D(5, 3)]
game[Stage2D][Entity('Player'):'player,hero']
game[Entity:'player'] = game[Stage2D][Entity:'player']

game[Entity:'player'].spawn >> (lambda entity: print(f'{entity.name} spawned!'))
game.start >> [
    game[Stage2D][Entity:'*'].spawn,
    lambda game: print(f'{game.name} started!'),
]
game.start()
```

Read [TUTORIAL.md](TUTORIAL.md) for selectors, numbered IDs, links, custom components, and save/load. Run `python test.py` for a compact turn-based example. Existing signal and session APIs remain supported.

### Grid input and movement

A grid controller needs one connection:

```python
from silicon import Game, Stage2D, InputMap, GridMovement

game = Game()
game.add(Stage2D(20, 12), id='stage')
game.add(InputMap(), id='keys')
game.add(GridMovement(), id='movement')
game['keys'].out.action >> game['movement'].ins.command
game.start()
game['stage'].ins.place('hero', 0, 0)
game['keys'].ins.feed('d')
```

### Continuous movement and lifetime

For continuous movement and disposable projectiles:

```python
from silicon import Game, Transform2D, Gravity, Velocity, Collision2D, Lifetime

game = Game()
game.add(Transform2D(), id='transform')
game.add(Gravity(600, terminal_speed=900), id='gravity')
game.add(Velocity(), id='velocity')
game.add(Collision2D(), id='collisions')
game.add(Lifetime(), id='lifetime')
game['lifetime'].out.expired >> game['transform'].ins.remove
game['lifetime'].out.expired >> game['velocity'].ins.stop
game['lifetime'].out.expired >> game['gravity'].ins.remove
game['lifetime'].out.expired >> game['collisions'].ins.remove
game.start()
game['transform'].ins.place('ball', 100, 100)
game['velocity'].ins.set('ball', 80, -240)
game['gravity'].ins.add('ball')
game['collisions'].ins.add('ball', 16, 16)
game['lifetime'].ins.add('ball', 3)
game.step(1 / 60)  # Or drive Game.run() from your application's event loop.
```

Coordinates use positive y downward. Updates run in component insertion order:
add gravity before velocity and collision detection after velocity. Physics uses
Euler integration; collision detection is AABB overlap detection, without automatic
collision response or continuous/swept collision tests. Use small steps for fast
objects. `Stage2D` remains an integer grid; `Transform2D` stores continuous positions.

## Dependencies

- **Core:** Python 3.11+; `Session` uses the standard library.
- **Wednesware desktop / LAN integrations:** Python 3.12+.
- **Desktop:** [Fluorine 26.7+](https://github.com/Wednesware/Fluorine/releases/tag/26.7), [Sulfur 26.9+](https://github.com/Wednesware/Sulfur/releases/tag/26.9), `wwn`, `pywebview`, `PySide6`, `qtpy`, and a working Qt desktop backend on Linux.
- **LAN multiplayer:** [Beryllium](https://github.com/Wednesware/Beryllium), Fluorine, FastAPI, Uvicorn, and a WebSocket backend; Sulfur is not required.
- **Optional audio and shell:** [Carbon](https://github.com/Wednesware/Carbon) and [Iodine](https://github.com/Wednesware/Iodine).

# Guides

## Extended examples and optional integrations

Read `demo.py` for a comprehensive framework walkthrough made of actual code
with short comments, ending in a complete Snake game. Run `python demo.py --tour`
for executable examples without optional dependencies,
`python demo.py --reference` to print the commented source, or `python demo.py --snake`
to open Snake directly with Silicon's `App` (Sulfur + Fluorine). Snake supports
WASD/arrows, queued turns, growth, increasing speed, collisions, victory,
pause/resume, restart and save/load. Its default save is `snake_save.json`;
`--save PATH` and `--seed INTEGER` customize it. Desktop dependencies are below.

Run `python3 web_game.py` to open the Fluorine interface in a Sulfur desktop window.

For a fresh checkout, install Python 3.12+, `wwn`, `pywebview`, `PySide6`, and
`qtpy`. Install Fluorine 26.7+ and Sulfur 26.9+ through Nitrogen (`n2 get fluorine`
and `n2 get sulfur`). Linux also needs a working
Qt desktop backend. Run from a desktop session with display access.

Use WASD, arrow keys, or the on-screen arrows to reach the treasure at (4, 4).
Traps at (2, 1) and (3, 3) cost one health on each visit. Each valid move
advances the round timer by one second, matching the terminal game. Timer
expiry announces the round's end without ending the game, as in the original.
Save and Load use `treasure_save.json` in the working directory. New expedition
resets the game. Closing the window stops it.

`test.py` demonstrates the component/trigger syntax. The older desktop Treasure
Hunt example currently expects a `create_game()` factory that this file does not
provide; it needs that factory restored before it can run.
The desktop interface subclasses Silicon's `Session`,
mounts its page once, and passes that page directly to Sulfur's `App`.
Sulfur registers Fluorine's callbacks and waits for page
readiness before delivering DOM updates. Movement buttons use `functools.partial`
to bind their commands. Python callbacks update the game and Fluorine element tree.
The session reattaches the page after load/restart and stops the game when its
context exits. Pages and subscriptions are runtime objects and are not saved.

## Local Silicon session API

`Session` handles callback locking, save/load/restart, frontend reattachment,
status messages, and render subscriptions. It uses only the standard library;
Fluorine and Sulfur remain optional hosts.

```python
from silicon import Session
from test import create_game

with Session(create_game, 'treasure_save.json') as session:
    session.mount(page)  # Or mount(site, 'treasure') for a page collection.
    session.watch(render)  # Render immediately, then after each action/change.
    # UI buttons can call session.save, session.load, and session.restart directly.
    App(page).open()
```

Subclass `Session` for application-specific actions, as `TreasureInterface` does:

```python
class Controller(Session):
    @Session.action
    def take_turn(self):
        self.send('turns', 'advance')
        self.step(1.0)
        self.message = 'Turn complete.'
```

An action is synchronous and serialized against the session's other actions.
Nested input calls, signal chains, timer updates, and message changes produce one
render after the action finishes. `session.state('rules')` gives game-bound state
for the current game. `session.send(component, input_name, *args)` also resolves
the current game, so existing UI callbacks keep working after replacement.
Save/load return a success boolean and report file errors through `message`.
A failed load keeps the current game running; a successful load preserves the
saved running/paused state. The factory is used for initial creation and restart.

`session.watch(callback)` returns an unsubscribe function. Use `immediate=False`
to skip the initial render. `session.game_changed.connect(callback)` reports
`(previous_game, new_game)` when load or restart replaces the game.

For lower-level integrations, `game.changed.connect(callback)` observes component
inputs, outputs, lifecycle operations, steps, and `State` assignments. Use
`with game.batch():` to coalesce changes. In-place list/dictionary edits do not
invoke a state setter: perform them in a component input or a session action /
`with session.transaction():` so completion triggers a notification.

The session protects its own actions; direct concurrent calls on the underlying
`Game` are outside that lock. Read state in the current action or renderer rather
than retaining a bound component/state object across game replacements.

Library releases:
- [Fluorine 26.7](https://github.com/Wednesware/Fluorine/releases/tag/26.7)
- [Sulfur 26.9](https://github.com/Wednesware/Sulfur/releases/tag/26.9)

Validation with the dependencies installed:

```sh
python3 -m unittest discover -s tests
python3 -m compileall silicon test.py web_game.py
```

## Shared LAN multiplayer

```sh
python web_game.py --multiplayer --port 8000
# Bind only to this computer for local testing:
python web_game.py --multiplayer --host 127.0.0.1
```

Open `http://<host-LAN-IP>:8000` on each device. All players move the same hero
and share health, time, saves, and restart. Each browser tab remains a separate
Beryllium client. Controls work through Beryllium's Fluorine callback bridge;
keyboard controls click the same movement buttons. Every complete session
action renders once, then `refresh_page()` publishes the result to all viewers.

Install `n2 get beryllium` and its FastAPI/Uvicorn dependencies in addition to
Fluorine. The LAN mode does not need Sulfur or a desktop backend. Silicon itself
still supports Python 3.11+; these Wednesware integrations require Python 3.12+.
The adapter follows [Beryllium's Host and page callback API](https://github.com/Wednesware/Beryllium).

For another game, mount a Fluorine page whose callbacks use `@Session.action`,
then bind the component after registering the renderer:

```python
from silicon import Multiplayer

# session.mount(page)
# session.watch(render)
network = Multiplayer(port=8000).bind(session, page)
network.run(admin=False, sulfur=False)
```

`Multiplayer` prints the local URL and a `Hosting at` announcement with the
detected LAN URL when its binding runs, even without `--debug`.
This is enabled by default; use `Multiplayer(port=8000, print_url=False)` to
suppress URL output. The setting is retained in saved games.

`bind()` adds the component to the game and returns its runtime binding. The
binding exposes `host`, a `players` mapping keyed by Beryllium `full_id`, and
`action(name, callback)` for explicit HTTP/WebSocket commands. A command callback
receives the trusted player ID followed by keyword payload arguments and runs
under the session lock. For example:

```python
network.action('move', lambda player, direction: session.command(direction))
# Browser: beryllium.emit('move', {direction: 'd'})
# Or:     berylliumAction('move', {direction: 'd'})
```

The component outputs `connected(player)`, `disconnected(player)`, and
`command(player, name)` (the latter for explicitly registered commands).
Beryllium enforces its client active/paused state before dispatch. Only registered
callbacks are exposed. Use synchronous callbacks, as with `Session.action`.
Game replacement retains the host, routes, player registry, and page; connections
in saved games are restored normally. Host/client objects never enter saves.
Session closure detaches subscriptions and explicit routes; `run()` also detaches
on exit. The Beryllium server owns its blocking run loop (Ctrl+C stops the CLI).

## Optional desktop, audio, and shell adapters

Adapters load their dependencies only when used. Their configuration is saved;
windows, audio processes, terminal widgets, and attached pages are runtime only.

```python
from silicon import App, ShellInput, SoundEffects, SoundPlayer

# After session.mount(page), open a Sulfur window without backend setup code:
session.game.add(App(name='My game', width=900, height=650), id='app')
session['app'].ins.open()  # Blocks until closed; stops its game on exit/failure.

# Named WAV effects, played without blocking the game:
game.add(SoundEffects({'jump': 'jump.wav', 'coin': 'coin.wav'}), id='sounds')
game['sounds'].ins.play('jump')
game['sounds'].ins.stop('jump')

# Direct WAV paths, including pathlib.Path objects:
game.add(SoundPlayer(), id='audio')
game['audio'].ins.play('notification.wav')
game['audio'].ins.stop('notification.wav')
game['audio'].ins.stop_all()  # Stops paths requested by this player in this game.

# Plain shell input; iodine=True enables Iodine's editor/selection menu:
game.add(ShellInput(options=['left', 'right', 'quit'], iodine=True), id='shell')
game['shell'].out.submitted >> game['keys'].ins.feed
game['shell'].ins.read()  # Explicitly blocking; cancellation emits cancelled().
```

Install these integrations with `n2 get sulfur`, `n2 get carbon`, or
`n2 get iodine`. See the upstream [Sulfur window API](https://github.com/Wednesware/Sulfur),
[Carbon playback API](https://github.com/Wednesware/Carbon), and
[Iodine widgets](https://github.com/Wednesware/Iodine) for platform dependencies.
Carbon playback occurs on the host machine. Stopping a game stops the files it
played; Carbon's file-level stopping can also affect another game playing the
same path. Browser audio would require a separate browser-side audio adapter.
Carbon requires Python 3.12+, Nitrogen 26.63+, and `alsa-utils` (`aplay`) on Linux.

## Validation

```sh
python -m unittest discover -s tests
python -m compileall silicon test.py web_game.py tests
```

The existing web tests need Fluorine installed. With the adjacent source checkout,
use `PYTHONPATH=../sf/fluorine .venv/bin/python -m unittest discover -s tests`.
The new adapter tests inject backend doubles and require no window, speaker,
TTY, network, or optional library installation.

## Command-line options

`CommandOptions` captures `sys.argv[1:]`, or accepts an explicit argument list.
Query option aliases dynamically or use an integer for a positional argument:

```python
from silicon import CommandOptions

# python game.py level.json --host localhost -p 8000 --debug
options = CommandOptions(flags=['--debug'])
host = options.get('--host', '-h', default='127.0.0.1')
port = int(options.get('--port', '-p', default='8000'))
level = options.get(0, default='default.json')
debug = options.get('--debug', default=False)
# options.positionals contains all positional arguments.
```

Both `--host localhost` and `--host=localhost` work. Values stay strings;
valueless options return `True`, missing values return the supplied default
(`None` by default), and the last occurrence across aliases wins. Register
boolean options with `flags=[...]` so they do not consume the next positional
argument. Without a schema, an option followed by a plain token takes that token
as its value. Negative numbers are accepted as values or positionals. Use
`--name=-value` for other values beginning with a dash. A standalone `--` makes
all remaining tokens positional. Short options are exact names; bundles such as
`-abc` are not expanded. Negative positional indexes work like Python lists.

The component can also be added to a game and queried through
`game['options'].ins.get('--host', '-h')`. Captured arguments are serialized, so
loading a game preserves its options instead of reading the loading process's
command line.

### Multiplayer shows a blank page or refuses `/ws`

Beryllium initially serves a shell and delivers the game over WebSockets.
Uvicorn's minimal installation can serve HTTP without a WebSocket backend,
which leaves the shell blank. Install the multiplayer dependencies into the
same environment used to run the game, then restart:

```sh
.venv/bin/python -m pip install -r requirements-multiplayer.txt
.venv/bin/python web_game.py --multiplayer --debug
```

For an existing installation, `python -m pip install websockets` supplies the
missing transport. Silicon now checks Uvicorn's selected WebSocket backend
before starting its built-in host and reports missing support immediately.
`--debug` enables Beryllium/Uvicorn diagnostics, including handshake failures and
server exceptions. Open `http://127.0.0.1:8000` locally after startup. If `/ws`
still fails, inspect the server terminal for the rejection or traceback; browser
connection errors alone do not identify cookie, origin, or rendering failures.



# Definitions

## `silicon`

From the base library, import the framework objects used below, including `Game`, `Stage2D`, `Entity`, `Session`, `Multiplayer`, `CommandOptions`, and the gameplay and adapter components.

> `from silicon import Game, Stage2D, Entity, Session, Multiplayer, CommandOptions`

### `silicon:Game(name, seed)`

Creates a game. Components can be attached, selected by type or ID, and connected with typed triggers. The quick-start example demonstrates a named game and deterministic seed. Use `game.start()` to start and `game.step(dt)` to advance time; `game.changed.connect(callback)` observes changes. The original README does not specify the full constructor signature.

> `game = Game('SnakeGame', seed=7)`

### `silicon:Session(factory, save_path)`

Coordinates synchronous, serialized UI actions, saves, loads, restarts, frontend attachment, status messages, and render subscriptions. The factory supplies the initial game and restart instances. Save/load return a success boolean; failures are reported through `message` without discarding the current game. Successful loads preserve the saved running/paused state.

> `with Session(create_game, 'treasure_save.json') as session:`

#### `silicon:Session.mount(page)`

Attaches a frontend page. A page collection can be mounted using `mount(site, 'treasure')`. Pages and subscriptions are runtime objects, not saved.

> `session.mount(page)`

#### `silicon:Session.watch(callback)`

Subscribes a renderer and invokes it immediately by default. `immediate=False` skips the first render. Returns an unsubscribe function.

> `unsubscribe = session.watch(render)`

#### `silicon:Session.send(component, input_name, *args)`

Resolves the component against the current game, including after a load or restart.

> `session.send('turns', 'advance')`

#### `silicon:Session.state(component)`

Retrieves game-bound state for the current game; do not retain stale bound objects across game replacements.

> `rules = session.state('rules')`

#### `silicon:Session.action`

Decorator for a serialized synchronous session action. Nested inputs, signal chains, timer updates, and message changes trigger one render on completion.

> `@Session.action`

#### `silicon:Session.transaction()`

Groups mutations, including in-place list or dictionary updates, so completion notifies observers.

> `with session.transaction():`

### `silicon:Multiplayer(port=8000, print_url=True)`

Creates the Beryllium-backed LAN host component. The default binding announces local and detected LAN URLs; `print_url=False` suppresses this. Configuration is saved while host/client instances remain runtime-only. The source also describes outputs `connected(player)`, `disconnected(player)`, and `command(player, name)`.

> `network = Multiplayer(port=8000).bind(session, page)`

#### `silicon:Multiplayer.bind(session, page)`

Adds the component to the game and returns a runtime binding exposing `host`, a `players` mapping keyed by Beryllium `full_id`, and `action(name, callback)`. Connections and pages remain active across game replacement.

> `network = Multiplayer(port=8000).bind(session, page)`

#### `silicon:Multiplayer.run(admin=False, sulfur=False)`

Starts the blocking server loop. Calling `run()` also detaches its runtime binding on exit; Ctrl+C stops the CLI.

> `network.run(admin=False, sulfur=False)`

#### `silicon:Multiplayer.action(name, callback)`

Registers an explicit HTTP/WebSocket command callback. The callback receives the trusted player ID followed by keyword payload arguments and executes under the session lock; unregistered callbacks are not exposed.

> `network.action('move', lambda player, direction: session.command(direction))`

## Gameplay components

All the following components are available directly from `silicon`, have stable save registrations, and keep mutable gameplay state separate for each game. Call inputs through `game['id'].ins` and connect outputs with `>>`.

### `silicon:InputMap(bindings=None)`

`feed(key)` maps WASD/arrows by default to `action(direction)`; custom dictionaries support any named action.

### `silicon:GridMovement(entity='hero', stage_id='stage')`

`command(direction)` or `move(dx, dy)` on a `Stage2D`; emits `moved` or `blocked`, returns success. `solid(entity)` marks occupied cells as walls.

### `silicon:Transform2D()`

Continuous positions via `place(entity, x, y)`, relative `move(entity, dx, dy)`, and `remove(entity)`; emits `moved`/`removed`.

### `silicon:Velocity(transform_id='transform')`

`set(entity, vx, vy)`, `accelerate(entity, dvx, dvy)`, `stop(entity)`; integrates positions each step.

### `silicon:Gravity(acceleration=9.8, velocity_id='velocity', terminal_speed=None)`

`add(entity)`/`remove(entity)` select affected entities; accelerates downward each step.

### `silicon:Collision2D(transform_id='transform')`

`add(entity, width=1, height=1)`/`remove(entity)`; emits `entered(a, b)` and `exited(a, b)` once per contact change.

### `silicon:Health()`

`add(entity, maximum=3)`, `damage(entity, amount=1)`, `heal(entity, amount=1)`; clamps health and emits `changed(entity, value)` and `died(entity)` on reaching zero.

### `silicon:Inventory()`

`add(item, count=1)` and `take(item, count=1)`; emits `changed(item, count)` or `missing(item)`, returns success from `take`.

### `silicon:Score()`

`add(amount=1)`/`reset()`; emits `changed(value)`.

### `silicon:Lifetime()`

`add(entity, seconds)`/`remove(entity)`; emits `expired(entity)` once when its countdown reaches zero.


## Optional adapters

### `silicon:App(name, width, height)`

Sulfur-backed desktop application. Opening blocks until closure and stops its game on exit or failure. Configuration is saved; windows and pages are runtime-only.

> `session.game.add(App(name='My game', width=900, height=650), id='app')`

#### `silicon:App.open()`

> `session['app'].ins.open()`

### `silicon:SoundPlayer(prevent_overlap=True)`

Direct WAV playback via [Carbon](https://github.com/Wednesware/Carbon/blob/main/README.md)
without blocking the game. `play(path)` accepts a filename or `pathlib.Path`;
`stop(path)` stops a path requested by this player in the current game, and
`stop_all()` stops all of its requested paths. `prevent_overlap=True` asks Carbon
to stop the same file before replaying it. Outputs `played(path)` and
`stopped(path)` report explicit playback requests and stops; `played` does not
indicate completion or successful audio output. Carbon handles playback errors
in its background thread.

Game stop and component removal stop tracked paths. Saves preserve configuration
without saving or resuming playback. Carbon is loaded only on playback; install
it with `n2 get carbon`. Playback occurs on the host machine. Carbon stops by
filename, so stopping a shared path can affect other players or games; on Windows,
its stop operation stops the sound device.

> `game.add(SoundPlayer(), id='audio')`

### `silicon:SoundEffects(effects)`

Named WAV playback via Carbon without blocking the game. `play(name)` plays an effect and `stop(name)` stops it. Playback occurs on the host machine and file-level stopping may affect another game playing the same path.

> `game.add(SoundEffects({'jump': 'jump.wav', 'coin': 'coin.wav'}), id='sounds')`

### `silicon:ShellInput(options, iodine=True)`

Blocking terminal input; `iodine=True` enables Iodine's editor/selection menu. Emits `submitted` and `cancelled()` on cancellation.

> `game.add(ShellInput(options=['left', 'right', 'quit'], iodine=True), id='shell')`

### `silicon:CommandOptions(flags=None)`

Captures `sys.argv[1:]` or an explicit argument list. Registered boolean flags do not consume a positional argument. Values stay strings; valueless options return `True`. Arguments are serialized when the component belongs to a game.

> `options = CommandOptions(flags=['--debug'])`

#### `silicon:CommandOptions.get(*aliases, default=None)`

Reads option aliases or a numeric positional index. Missing options return `default`; the last matching alias wins. Exact short options are not bundled. Negative indexes work like list indexes.

> `host = options.get('--host', '-h', default='127.0.0.1')`
