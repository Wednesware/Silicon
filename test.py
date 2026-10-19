"""Run a small game demonstrating Silicon's component and trigger syntax."""
from silicon import Component, Effect, Entity, Game, Stage2D, TurnManager, trigger


class Greeter(Component):
    def __component__(self, greeting='hello'):
        self.greeting = greeting

    @trigger
    def greet(self):
        print(f'{self.greeting} id:{self.id} game:{self.game.name}, parent:{self.parent.id}')


def main():
    game = Game('SnakeGame', seed=7)
    game[Stage2D(5, 3)]
    game[Stage2D][Entity('Player'):'player,hero']
    game[Entity:'player'] = game[Stage2D][Entity:'player']
    game[Greeter('hi'):'greeter#']
    game[TurnManager()]

    game[Entity:'player'].spawn >> (lambda entity: print(f'{entity.name} spawned!'))
    game.start >> [
        game[Stage2D][Entity:'*'].spawn,
        lambda game: print(f'{game.name} started!'),
        lambda game: game[Entity:'player'][Effect('protection', 1, 2):'#'],
        game[Greeter:'greeter0'].greet,
    ]
    game[TurnManager].next_turn >> [
        lambda game, entity: game[Entity:entity.id][Effect:'*'].proc(),
        lambda game, entity: game[Entity:entity.id][Effect:'*'].reduce_remaining_turns(1),
    ]
    game.start()
    for turn in range(1, 3):
        game[TurnManager].next_turn(entity=game[Entity:'player'].component)
        print(f'Turn {turn}: {len(game[Entity:"player"][Effect:"*?"] or ())} active effects')
    game.stop()


if __name__ == '__main__':
    main()
