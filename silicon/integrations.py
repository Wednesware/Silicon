"""Optional Wednesware adapters. Dependencies load only when an adapter is used."""
import builtins
import importlib
import os
import socket

from . import Component, State, input, output, register


def dependency(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
    try:
        from nitrogen import require
    except ImportError as exc:
        raise ImportError(f'Install {name} with `n2 get {name}` to use this adapter') from exc
    return require(name)


@register('silicon.App')
class App(Component):
    """Blocking Sulfur window. Pages and native windows never enter game saves."""
    def __init__(self, frontend_id='frontend', **window_options):
        super().__init__()
        self.frontend_id = frontend_id
        self.window_options = window_options
        self.window = None

    def to_config(self):
        return dict(frontend_id=self.frontend_id, **self.window_options)

    @input
    def open(self, dev=False):
        if self.window is not None:
            raise RuntimeError('App is already open')
        game = self._active_game
        page = game.get(self.frontend_id).page(game)
        if page is None:
            raise RuntimeError('Attach a page to FrontEnd before opening App')
        self.window = dependency('sulfur').App(page, **self.window_options)
        try:
            self.out.opened()
            return self.window.open(dev=dev)
        finally:
            self.window = None
            game.stop()
            self.out.closed()

    @input
    def close(self):
        if self.window is not None:
            self.window.close()

    @output
    def opened(self): pass

    @output
    def closed(self): pass


@register('silicon.SoundPlayer')
class SoundPlayer(Component):
    """Nonblocking Carbon WAV playback by path; playback is runtime only."""
    def __init__(self, prevent_overlap=True):
        super().__init__()
        self.prevent_overlap = bool(prevent_overlap)
        self._playing = {}

    def to_config(self):
        return {'prevent_overlap': self.prevent_overlap}

    @input
    def play(self, path):
        """Request playback of a WAV filename or pathlib.Path."""
        path = os.fsdecode(path)
        dependency('carbon').play_thread(path, prevent_overlap=self.prevent_overlap)
        self._playing.setdefault(self._active_game, set()).add(path)
        self.out.played(path)

    @input
    def stop(self, path):
        """Stop a path requested by this player in the active game."""
        path = os.fsdecode(path)
        paths = self._playing.get(self._active_game, set())
        if path in paths:
            dependency('carbon').stop(path)
            paths.remove(path)
            self.out.stopped(path)

    @input
    def stop_all(self):
        """Stop this game's requested paths without calling Carbon's stop_all."""
        for path in tuple(self._playing.get(self._active_game, ())):
            self.stop(path)

    def on_stop(self, game):
        paths = self._playing.get(game)
        if paths:
            carbon = dependency('carbon')
            for path in tuple(paths):
                carbon.stop(path)
                paths.remove(path)
        self._playing.pop(game, None)

    def on_detach(self, game):
        self.on_stop(game)

    @output
    def played(self, path: str): pass

    @output
    def stopped(self, path: str): pass


@register('silicon.SoundEffects')
class SoundEffects(Component):
    """Named, nonblocking Carbon WAV effects; stop only this adapter's sounds."""
    def __init__(self, sounds=None, prevent_overlap=True):
        super().__init__()
        self.sounds = dict(sounds or {})
        self.prevent_overlap = bool(prevent_overlap)
        self._playing = {}

    def to_config(self):
        return dict(sounds=self.sounds, prevent_overlap=self.prevent_overlap)

    @input
    def play(self, name: str):
        path = self.sounds[name]
        dependency('carbon').play_thread(path, prevent_overlap=self.prevent_overlap)
        self._playing.setdefault(self._active_game, set()).add(path)
        self.out.played(name)

    @input
    def stop(self, name: str):
        path = self.sounds[name]
        dependency('carbon').stop(path)
        self._playing.get(self._active_game, set()).discard(path)

    def on_stop(self, game):
        paths = self._playing.pop(game, set())
        if paths:
            carbon = dependency('carbon')
            for path in paths:
                carbon.stop(path)

    def on_detach(self, game): self.on_stop(game)

    @output
    def played(self, name: str): pass


@register('silicon.ShellInput')
class ShellInput(Component):
    """Explicit blocking prompts; feed() also supports scripted input without a TTY."""
    def __init__(self, prompt='> ', options=None, iodine=False):
        super().__init__()
        self.prompt = prompt
        self.options = None if options is None else list(options)
        self.iodine = bool(iodine)

    def to_config(self):
        return dict(prompt=self.prompt, options=self.options, iodine=self.iodine)

    @input
    def feed(self, value: str):
        if self.options is not None and value not in self.options:
            self.out.invalid(value)
            return False
        self.out.submitted(value)
        return True

    @input
    def read(self):
        try:
            if self.iodine:
                iodine = dependency('iodine')
                widgets = importlib.import_module(iodine.__name__ + '.widgets')
                widget = (widgets.SelectMenu(self.options, title=self.prompt)
                          if self.options is not None else widgets.TextInput(prompt=self.prompt))
                value = iodine.run(widget)
            else:
                value = builtins.input(self.prompt)
        except (EOFError, KeyboardInterrupt):
            value = None
        if value is None:
            self.out.cancelled()
            return None
        self.feed(value)
        return value

    @output
    def submitted(self, value: str): pass

    @output
    def invalid(self, value: str): pass

    @output
    def cancelled(self): pass


def _print_multiplayer_urls(host, port):
    Color = dependency('mg.color').Color
    if host == '0.0.0.0':
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
                # Select the default network interface without sending packets.
                connection.connect(('192.0.2.1', 80))
                address = connection.getsockname()[0]
            print(f'{Color.lime}Hosting at http://{address}:{port}{Color.reset}', flush=True)
        except OSError:
            print(f"{Color.lime}Could not determine LAN IP address. Port: {port}{Color.reset}", flush=True)
    else:
        address = f'[{host}]' if ':' in host else host
        print(f'{Color.lime}Hosting at http://{address}:{port}{Color.reset}', flush=True)


@register('silicon.Multiplayer')
class Multiplayer(Component):
    """One authoritative Session shared by all Beryllium clients.

    bind(session, page) returns a runtime binding. Call binding.run() to host.
    Startup URLs are printed by default; set print_url=False to disable them.
    Page callbacks should be @Session.action methods. The binding survives game
    replacement; hosts, clients and subscriptions are deliberately not serialized.
    """
    def __init__(self, port=8000, host='0.0.0.0', max_clients=None, print_url=True):
        super().__init__()
        self.port, self.host, self.max_clients = port, host, max_clients
        self.print_url = bool(print_url)

    def to_config(self):
        return dict(port=self.port, host=self.host, max_clients=self.max_clients,
                    print_url=self.print_url)

    def bind(self, session, page=None, *, host=None):
        return MultiplayerBinding(self, session, page, host=host)

    @output
    def connected(self, player: str): pass

    @output
    def disconnected(self, player: str): pass

    @output
    def command(self, player: str, name: str): pass


class MultiplayerBinding:
    def __init__(self, component, session, page=None, *, host=None):
        self.session = session
        self._uses_uvicorn = host is None
        self.host = host if host is not None else dependency('beryllium').Host(
            port=component.port, host=component.host, max_clients=component.max_clients,
            admin_panel=False)
        self.players = {}
        self._closed = False
        self._routes = []
        self._subscriptions = []
        self.component_id = next((k for k, c in session.game.components.items() if c is component), 'multiplayer')
        if self.component_id not in session.game.components:
            session.game.add(component, id=self.component_id)
        elif session.game.get(self.component_id) is not component:
            raise ValueError('multiplayer ID is already in use')
        if page is None:
            page = session.game.get('frontend').page(session.game)
        if page is None:
            raise ValueError('Multiplayer requires a page')
        self.page = page
        self.host.page = page
        self.host.on_connect(self._connected)
        self.host.on_disconnect(self._disconnected)
        self._subscriptions.append(session.game_changed.connect(self._replaced))
        self._subscriptions.append(session.closed.connect(self.close))
        # Subscribe after the application's renderer so refreshed HTML is final.
        self._subscriptions.append(session.watch(self.refresh, immediate=False))
        self._config = component.to_config()

    def _replaced(self, previous, game):
        if self.component_id not in game.components:
            game.add(Multiplayer(**self._config), id=self.component_id)
        if not isinstance(game.get(self.component_id), Multiplayer):
            raise TypeError('Multiplayer component ID must reference Multiplayer')

    def _signal(self, name, *args):
        getattr(self.session[self.component_id].out, name)(*args)

    def _connected(self, client):
        if self._closed:
            return
        with self.session.transaction():
            player = str(client.full_id)
            if player not in self.players:
                self.players[player] = client
                self._signal('connected', player)

    def _disconnected(self, client):
        if self._closed:
            return
        with self.session.transaction():
            player = str(client.full_id)
            if self.players.pop(player, None) is not None:
                self._signal('disconnected', player)

    def action(self, name, callback):
        """Expose one explicit callable over HTTP and WebSocket; inject trusted client ID.

        callback(player_id, **payload) runs under the session lock. No component
        names or arbitrary input slots are accepted from the browser.
        """
        if self._closed:
            raise RuntimeError('Multiplayer binding is closed')
        if name in self.host.actions or name in self.host.events:
            raise ValueError(f'Action already registered: {name}')
        def dispatch(client, **payload):
            if self._closed:
                raise RuntimeError('Multiplayer binding is closed')
            with self.session.transaction():
                player = str(client.full_id)
                result = callback(player, **payload)
                self._signal('command', player, name)
                return result
        self.host.action(name)(dispatch)
        self.host.on(name)(dispatch)
        self._routes.append((name, dispatch))
        return dispatch

    def refresh(self):
        if not self._closed:
            self.host.refresh_page(self.page)

    def run(self, **options):
        if self._closed:
            raise RuntimeError('Multiplayer binding is closed')
        try:
            if self._uses_uvicorn:
                auto = importlib.import_module('uvicorn.protocols.websockets.auto')
                if auto.AutoWebSocketsProtocol is None:
                    raise RuntimeError(
                        'Multiplayer needs a Uvicorn WebSocket backend. Install it in '
                        'the same Python environment: python -m pip install websockets '
                        '(or python -m pip install "uvicorn[standard]"). '
                        'Then restart the multiplayer server.')
            if self._config['print_url']:
                _print_multiplayer_urls(self._config['host'], self._config['port'])
            return self.host.run(**options)
        finally:
            self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        for unsubscribe in self._subscriptions:
            unsubscribe()
        self._subscriptions.clear()
        # Beryllium has no public unsubscribe API for connection callbacks. Keep
        # those inert after closure, and remove our own explicit action routes.
        for name, callback in self._routes:
            if self.host.actions.get(name) is callback:
                del self.host.actions[name]
            if self.host.events.get(name) is callback:
                del self.host.events[name]
        self._routes.clear()
        self.players.clear()
