from asyncio import events
import asyncio
import argparse
import os
import datetime

import pyglet
from pyglet.gl import *
from pyglet.window import key

from helpers import TERRITORY_CACHE, load_image
from clients import KeyboardClient, SimplePythonClient, FileClient
from constants import HOST_NAME, LR_CLIENT_WAIT_TIMEOUT, LR_CLIENTS_MAX_COUNT, MAX_TICK_COUNT, WINDOW_WIDTH, WINDOW_HEIGHT
from game_objects.scene import Scene
from game_objects.game import Game, LocalGame



parser = argparse.ArgumentParser(description='LocalRunner for paperio')

for i in range(1, LR_CLIENTS_MAX_COUNT + 1):
    parser.add_argument('-p{}'.format(i), '--player{}'.format(i), type=str, nargs='+',
                        help='Path to executable with strategy for player {}'.format(i))
    parser.add_argument('--p{}l'.format(i), type=str, nargs='?', help='Path to log for player {}'.format(i))

parser.add_argument('-t', '--timeout', type=str, nargs='?', help='off/on timeout', default='on')
parser.add_argument('-s', '--scale', type=int, nargs='?', help='window scale (%)', default=100)
parser.add_argument('-el', '--check_execution_limit', type=str, nargs='?', help='off/on check execution limit', default='on')
parser.add_argument('-mtc', '--max_tick_count', type=int, nargs='?', help='Max tick count', default=1500)
parser.add_argument('-c', '--console', type=str, nargs='?', help='on/off run as console without drawing game objects.', default='off')

args = parser.parse_args()

global MAX_TICK_COUNT
MAX_TICK_COUNT = args.max_tick_count

scene = Scene(args.scale, visible=args.console == 'off')
loop = events.new_event_loop()
events.set_event_loop(loop)

tcpClient = None
async def handle_connection(reader, writer):
    global tcpClient
    tcpClient = TcpClient(reader, writer, args.check_execution_limit == 'on')

async def client_wait_timeout():
    end_time = datetime.datetime.now() + datetime.timedelta(0, LR_CLIENT_WAIT_TIMEOUT);
    while not tcpClient and datetime.datetime.now() < end_time:
        await asyncio.sleep(0.1)
        
def wait_client(port):
    global tcpClient
    tcpClient = None
    
    loop = asyncio.get_event_loop()
    server = asyncio.start_server(handle_connection, LR_HOST_NAME, port, loop=loop)
    loop.run_until_complete(server)
    loop.run_until_complete(client_wait_timeout())
    
    if tcpClient:
        loop.run_until_complete(tcpClient.set_solution_id())
        
    return tcpClient


clients = []
for i in range(1, LR_CLIENTS_MAX_COUNT + 1):
    arg = getattr(args, 'player{}'.format(i))
    if arg:
        if arg[0] == 'keyboard':
            client = KeyboardClient(scene.window)
        elif arg[0] == 'simple_bot':
            client = SimplePythonClient()
        elif arg[0] == 'tcpclient':
            if len(arg) < 2:
                raise ValueError("Port number is required for tcp client.")
            port = int(arg[1])
            client = wait_client(port);
        else:
            client = FileClient(arg[0].split(), getattr(args, 'p{}l'.format(i)))

        if client:
            clients.append(client)

if len(clients) == 0:
    clients.append(KeyboardClient(scene.window))
    
class Runner:
    @staticmethod
    def game_over_loop(dt):
        Runner.game.scene.clear()
        Runner.game.draw()

    @staticmethod
    def game_loop_wrapper(dt):
        is_game_over = loop.run_until_complete(Runner.game.game_loop())
        if is_game_over or (args.timeout == 'on' and Runner.game.tick >= MAX_TICK_COUNT):
            loop.run_until_complete(Runner.game.game_loop())
            Runner.game.send_game_end()
            Runner.game.game_save()
            Runner.stop_game()

    @staticmethod
    @scene.window.event
    def on_key_release(symbol, modifiers):
        if symbol == key.R:
            Runner.stop_game()
            TERRITORY_CACHE.clear()
            Runner.run_game()

    @staticmethod
    @scene.window.event
    def on_resize(width, height):
        (actual_width, actual_height) = scene.window.get_viewport_size()
        glViewport(0, 0, actual_width, actual_height)
        glMatrixMode(gl.GL_PROJECTION)
        glLoadIdentity()

        factScale = max(WINDOW_WIDTH / actual_width, WINDOW_HEIGHT / actual_height)
        xMargin = (actual_width * factScale - WINDOW_WIDTH) / 2
        yMargin = (actual_height * factScale - WINDOW_HEIGHT) / 2
        glOrtho(-xMargin, WINDOW_WIDTH + xMargin, -yMargin, WINDOW_HEIGHT + yMargin, -1, 1)
        glMatrixMode(gl.GL_MODELVIEW)
        return pyglet.event.EVENT_HANDLED

    @staticmethod
    def stop_game():
        pyglet.clock.schedule_interval(Runner.game_over_loop, 1 / 200)
        pyglet.clock.unschedule(Runner.game_loop_wrapper)

    @staticmethod
    def load_sprites():
        base_dir = os.path.dirname(os.path.realpath(__file__))
        absolute_path = os.path.join(base_dir, 'sprites')
        sprites = os.listdir(absolute_path)
        for sprite in sprites:
            if sprite.endswith('png'):
                load_image('sprites/{}'.format(sprite))

    @staticmethod
    def run_game():
        pyglet.clock.unschedule(Runner.game_over_loop)
        Runner.load_sprites()
        Runner.game = LocalGame(clients, scene, args.timeout == 'on')
        if args.console == 'off':
            Runner.game = LocalGame(clients, scene, args.timeout == 'on')
        else:
            Runner.game = Game(clients)
        Runner.game.send_game_start()
        pyglet.clock.schedule_interval(Runner.game_loop_wrapper, 1 / 200)


Runner.run_game()

if args.console == 'off':
    scene.window.set_visible(False)
    
pyglet.app.run()
