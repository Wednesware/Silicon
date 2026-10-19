# Learn Silicon one step at a time

Silicon lets you build a game from small objects called **components**.
Start with a game, add a component, and then give it something to do.

You need Python 3.11 or newer and basic Python knowledge. The examples here use
only the standard library. Create `my_game.py` in this repository and run it with:

```sh
python3 my_game.py
```

Steps 1–6 build one small example. Each step explains what to change, and step 6
includes the complete file. The later sections are optional additions.

## 1. Create a game

Put this in `my_game.py`:

```python
from silicon import Game


game = Game('My first game')
game.start()
print(game.name)
game.stop()
```

Run the file. You should see:

```text
My first game
```

`Game` holds your game's components. `start()` marks the game as running;
`stop()` ends it. Starting a game does not open a window or start a loop.

## 2. Add one component

A stage describes the size of a board. Add `Stage2D` to your import:

```python
from silicon import Game, Stage2D
```

Insert these lines before `game.start()`:

```python
game[Stage2D(5, 3)]
print(game[Stage2D].width)
```

The new print shows `5`.

These two bracket expressions do different jobs:

- `game[Stage2D(5, 3)]` creates and adds a stage.
- `game[Stage2D]` finds that stage so you can read its attributes.

The parentheses create the component. Leaving them out looks up its type.
A component added without an ID is the only component of its exact type in that
location. Silicon calls this a **singleton**.

## 3. Put a component inside another component

Add `Entity` to the import:

```python
from silicon import Game, Stage2D, Entity
```

An entity can represent a player, enemy, or another object in your game.
After adding the stage, add a player inside it:

```python
game[Stage2D][Entity('Player')]
print(game[Stage2D][Entity].name)
```

The new print shows `Player`.

Read the brackets from left to right: find the stage, then add or find an entity
inside it. Your game now has this structure:

```text
Game
└── Stage2D
    └── Entity: Player
```

This creates the structure of a game. It does not draw the player on screen.

## 4. Give the player an ID

To allow several entities in the stage, give each one an ID.
**Replace** the two entity lines from step 3 with:

```python
game[Stage2D][Entity('Player'):'player']
player = game[Stage2D][Entity:'player']
print(player.name)
```

`'Player'` is the entity's display name. `'player'` is the ID you use to find it.
The colon introduces that ID.

The `player` variable keeps the following examples short. It holds a selector
for this location; you can use it to access the entity or its children.

You can now add another entity with a different ID:

```python
game[Stage2D][Entity('Guard'):'guard']
```

IDs only need to be unique for the same component type under the same parent.
Adding another `Entity` with ID `'player'` under this stage raises `KeyError`.

## 5. Run a trigger and respond to it

An entity has a `spawn` trigger. Before `game.start()`, try:

```python
player.spawn()
print(player.spawned)  # True
```

Calling a trigger runs its method. `spawn()` sets the entity's `spawned` flag.

You can also connect a function that runs afterward. Replace those two lines
with:

```python
def announce_spawn(entity):
    print(f'{entity.name} spawned!')


player.spawn >> announce_spawn
player.spawn()
```

You should see `Player spawned!`.

`>>` connects an action; it does not run it yet. `player.spawn()` runs the trigger
and then the connected action.

Silicon supplies the `entity` argument because the function asks for a parameter
with that name. An action can also ask for `game`, or take no arguments at all.

## 6. Spawn the player when the game starts

Remove the manual `player.spawn()` call and connect it to `game.start` instead:

```python
game.start >> player.spawn
```

Use `player.spawn` without parentheses when connecting it. Parentheses would
call it immediately.

Here is the complete file so far. You can replace `my_game.py` with this:

```python
from silicon import Game, Stage2D, Entity


game = Game('My first game')
game[Stage2D(5, 3)]
game[Stage2D][Entity('Player'):'player']
game[Stage2D][Entity('Guard'):'guard']
player = game[Stage2D][Entity:'player']


def announce_spawn(entity):
    print(f'{entity.name} spawned!')


player.spawn >> announce_spawn
game.start >> player.spawn

game.start()
print(game.name)
game.stop()
```

Output:

```text
Player spawned!
My first game
```

The guard stays unspawned because you connected only the player's trigger.
You now know the core pattern: add a component, find it, and connect a trigger.

## 7. Run several actions in order

For the next examples, keep editing the complete file above. Put new setup code
before the final `game.start()` call.

Define one more function:

```python
def announce_start(game):
    print(f'{game.name} started!')
```

Replace `game.start >> player.spawn` with a list of actions:

```python
game.start >> [
    player.spawn,
    announce_start,
]
```

The player spawns first, including its announcement. Then `announce_start` runs.

For a short action, you can use Python's `lambda` syntax instead of a named
function. This connection does the same thing:

```python
game.start >> [
    player.spawn,
    lambda game: print(f'{game.name} started!'),
]
```

Use one version, so you do not connect the same actions twice. When a lambda
appears directly after `>>`, Python requires parentheses around it:

```python
# An alternative to the announce_spawn connection from step 5:
player.spawn >> (lambda entity: print(f'{entity.name} spawned!'))
```

## 8. Write your own component

Add `Component` and `trigger` to your imports. Define this class before creating
`game`:

```python
class Greeter(Component):
    def __component__(self, greeting='hello'):
        self.greeting = greeting

    @trigger
    def greet(self):
        print(self.greeting)
```

`__component__` receives the constructor arguments. `@trigger` makes a method
callable and connectable with `>>`.

Add the component alongside your other game setup:

```python
game[Greeter('hi')]
game[Greeter].greet()  # Prints hi
```

Or replace that direct call with another startup connection:

```python
game.start >> game[Greeter].greet
```

Inside a component method, `self.game` refers to its game and `self.parent`
refers to the container where it was first added. For this greeter, both refer
to the game.

## 9. Make a shorter path

A link gives an existing component another location:

```python
game[Entity:'player'] = game[Stage2D][Entity:'player']
print(game[Entity:'player'].name)  # Player
```

Both paths reach the same entity and its children. The entity's original
`parent` stays the stage. Links use normal assignment.

A link must stay within one game and cannot create a cycle.

## 10. Select more than one entity

You can select several IDs by separating them with commas:

```python
characters = game[Stage2D][Entity:'player,guard']
for character in characters:
    print(character.name)
```

To select every entity in the stage, use `'*'`:

```python
characters = game[Stage2D][Entity:'*']
characters.spawn()
```

That runs `spawn` for each selected entity. To spawn all of them at startup,
replace the earlier startup connection with:

```python
game.start >> characters.spawn
```

Selectors look up their matches each time you use them. This wildcard will also
find entities added later.

An ID selector with no matches raises `LookupError` immediately:

```python
try:
    game[Stage2D][Entity:'missing']
except LookupError:
    print('No entity found')
```

If a missing entity is expected, add `?` at the end of the selector. Silicon
strips that suffix before matching and returns `None` if nothing is found:

```python
player = game[Stage2D][Entity:'player?']  # Finds the existing player
missing = game[Stage2D][Entity:'missing?']
print(missing is None)  # True

if missing is not None:
    missing.spawn()
```

The suffix also works with wildcards and numbered lookups, such as `'ghost*?'`
and `'#-1?'`. For comma-separated selectors, it applies to the whole lookup:
`'player,missing?'` returns the player, while `'absent,missing?'` returns `None`.
Without `?`, a comma-separated selector raises only if none of its branches
match. A retained selector is live too: using it after its last match is removed
raises `LookupError`, unless it was created with `?`.

Read attributes such as `.name` from a selection with exactly one match;
reading them from several matches raises `LookupError`.

### Match part of an ID

You can put `*` inside a selector too. It matches zero or more characters:

```python
game[Stage2D][Entity('Zombie'):'zombie0']
game[Stage2D][Entity('Another zombie'):'zombie1']

zombies = game[Stage2D][Entity:'zombie*']
zombies.spawn()  # Spawns both zombies
```

`'zombie*'` matches IDs starting with `zombie`. `'*0'` matches IDs ending with
`0`, and `'zombie*0'` matches IDs that start with `zombie` and end with `0`.
You can use more than one star, such as `'*zombie*'`.

Mix patterns and exact IDs in the same comma-separated selector:

```python
characters = game[Stage2D][Entity:'player,zombie*,*0']
characters.spawn()
```

Each matching entity is selected only once, even if several patterns or aliases
match it. Matching is case-sensitive and stays within the selected parent and
component type. Only `*` acts as a wildcard; a final `?` marks an optional lookup.
Use patterns when looking up components, and concrete IDs when creating or
linking them.

### Give one component several aliases

During creation, comma-separated IDs give **one entity** several names for lookup:

```python
game[Stage2D][Entity('Merchant'):'merchant,shopkeeper']
print(game[Stage2D][Entity:'shopkeeper'].name)  # Merchant
```

This creates one merchant. `.id` is its first ID; `.ids` contains all its aliases.
Selecting both aliases still selects that entity only once.

## 11. Generate numbered IDs

When you do not need to choose an ID yourself, use `'#'`:

```python
game[Stage2D][Entity('First enemy'):'#']   # ID '0'
game[Stage2D][Entity('Second enemy'):'#']  # ID '1'
```

Creation chooses the first unused nonnegative number for that type and parent.
You can look up an assigned number directly:

```python
print(game[Stage2D][Entity:0].name)  # First enemy
```

During lookup, `'#'` selects the last added numbered entity. `'#-1'` selects the
one before it:

```python
print(game[Stage2D][Entity:'#'].name)    # Second enemy
print(game[Stage2D][Entity:'#-1'].name)  # First enemy
```

A prefix makes a separate series:

```python
game[Stage2D][Entity('Third enemy'):'enemy#']   # ID 'enemy0'
game[Stage2D][Entity('Fourth enemy'):'enemy#']  # ID 'enemy1'
print(game[Stage2D][Entity:'enemy#'].name)     # Fourth enemy
```

Lookups follow insertion order, and creation can reuse freed numbers.

## 12. Add an effect to the player

Add `Effect` to your imports. Because `player` already selects the entity, you
can add a child without repeating the whole path:

```python
player[Effect('protection', value=1, turns=2):'shield']
shield = player[Effect:'shield']
print(shield.remaining_turns)  # 2
```

An effect stores a value and a number of remaining turns. Your rules decide
what the value does. Reduce the duration manually:

```python
shield.reduce_remaining_turns(1)
print(shield.remaining_turns)  # 1
shield.reduce_remaining_turns(1)
print(player[Effect:'shield?'] is None)  # True
```

At zero remaining turns, the effect removes itself.

### Create an effect when a trigger runs

To give protection at startup, use a function instead of adding it immediately:

```python
def give_protection(game):
    player = game[Stage2D][Entity:'player']
    player[Effect('protection', value=1, turns=2):'#']


game.start >> give_protection
```

Use this instead of the manual shield example above. The function runs when the
game starts. In a trigger list, use the function's name as an action.

Python evaluates expressions while building a list, so putting component
creation directly inside that list would create the effect immediately.
A lambda is another way to defer it, once you are comfortable with that syntax.

### Advance effects each turn

Add `TurnManager` to your imports and add this setup before `game.start()`:

```python
game[TurnManager()]


def advance_effects(game, entity):
    effects = game[Stage2D][Entity:entity.id][Effect:'*?']
    if effects is None:
        return
    effects.proc()
    effects.reduce_remaining_turns(1)


game[TurnManager].next_turn >> advance_effects
```

After `game.start()`, take a turn with:

```python
game[TurnManager].next_turn(entity=player.component)
```

`.component` retrieves the actual entity from its selector. The manager forwards
that `entity` argument to `advance_effects`. Call it twice to expire the
protection created by `give_protection`.

`proc()` is an effect trigger for your rules. After startup has created the
protection effect, connect this callback before taking turns. It asks for
`effect` and its ancestor `entity`:

```python
def report_effect(effect, entity):
    print(f'{entity.name}: {effect.name}')


game[Stage2D][Entity:'player'][Effect:'*'].proc >> report_effect
```

## 13. Keep changing values in State

Use `State` for mutable component values that need to survive saving. Add it to
your imports, then replace the `Greeter` class from step 8 with:

```python
class Greeter(Component):
    count = State(0, scope='game')

    def __component__(self, greeting='hello'):
        self.greeting = greeting

    @trigger
    def greet(self):
        self.count += 1
        print(f'{self.greeting}: greeting {self.count}')
```

Each call to `greet()` increases the count. `scope='game'` keeps that count
separate if you later share the same component object between games.

Ordinary attributes initialized in `__component__`, such as `greeting`, are
rebuilt from constructor configuration when loading. Use `State` for values
that change during play and must be restored.

## 14. Save and load

After creating the game and its components, you can save them:

```python
game.save('game.json')
restored = Game.load('game.json')
print(restored[Stage2D].width)  # 5
```

Saves preserve configuration, `State`, nesting, IDs, links, and random state.
**Trigger connections are not saved.** Reconnect actions on the restored game
before continuing play. Look components up through `restored`; selectors such
as `player` still refer to the original game.

Custom component classes register automatically. Import their defining modules
before loading them in another script. Keep saved values JSON-compatible.
For stable registration names and custom serialization, see the
[earlier API reference](LEGACY_TUTORIAL.md#step-3-save-constructor-settings).

## Where to go next

Run `python3 test.py` for a compact example combining these concepts. It is
more condensed than this walkthrough. Run `python3 demo.py --tour` for broader
examples, including the earlier signal API.

The [earlier API reference](LEGACY_TUTORIAL.md) covers `.ins`, `.out`, timed
updates, built-in component recipes, sessions, and optional interfaces.
These APIs remain supported; you can explore them when your game needs them.

A few details to keep handy:

- `Game('Name', seed=7)` gives repeatable randomness through `game.random`.
  `tick_rate` is an optional keyword for timed games.
- Trigger arguments are matched by parameter name. Besides `game`, `component`,
  and `parent`, callbacks can request component and ancestor types in snake case,
  such as `entity`, `effect`, or `turn_manager`. Named arguments from the emitting
  trigger are available too. Unmatched optional parameters keep their defaults;
  unmatched required parameters raise `TypeError`.
- Triggers and callbacks are synchronous. Feedback loops eventually raise
  `RuntimeError` at the game's signal limit.
- `pause`, `resume`, and `stop` are also game triggers. Lifecycle triggers emit
  once per state transition.
- Adding a component under several selected parents creates independent copies.
- `del game[Entity:'player']` removes that component, its original descendants,
  and links to them. Deleting a link also removes the underlying component.
