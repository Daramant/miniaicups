#!/usr/bin/env python3
from asyncio import events
import asyncio
import argparse
import os
import gzip
import json

import pyglet
from pyglet.gl import *
from pyglet.window import key
import datetime

from helpers import TERRITORY_CACHE, load_image
from clients import Client, KeyboardClient, SimplePythonClient, FileClient, TcpClient
from constants import CONSTS
from game_objects.game import LocalGame, Game
from game_objects.bonuses import Bonus
from game_objects.scene import Scene

parser = argparse.ArgumentParser(description='LocalRunner for paperio')

for i in range(1, CONSTS.LR_CLIENTS_MAX_COUNT + 1):
    parser.add_argument('-p{}'.format(i), '--player{}'.format(i), type=str, nargs='+', help='Path to executable with strategy for player {}'.format(i))
    parser.add_argument('--p{}l'.format(i), type=str, nargs='?', help='Path to log for player {}'.format(i))
    
parser.add_argument('-t', '--timeout', type=str, nargs='?', help='off/on timeout', default='on')
parser.add_argument('-s', '--scale', type=int, nargs='?', help='window scale (%%)', default=100)
parser.add_argument('-el', '--check_execution_limit', type=str, nargs='?', help='off/on check execution limit', default='on')
parser.add_argument('-mtc', '--max_tick_count', type=int, nargs='?', help='Max tick count', default=1500)
parser.add_argument('-c', '--console', type=str, nargs='?', help='on/off run as console without drawing game objects.', default='off')
parser.add_argument('--replay', help='Replay visio.gz')

args = parser.parse_args()

CONSTS.MAX_TICK_COUNT = args.max_tick_count

loop = events.new_event_loop()
events.set_event_loop(loop)

tcpClient = None
async def handle_connection(reader, writer):
    global tcpClient
    tcpClient = TcpClient(reader, writer, args.check_execution_limit == 'on')

async def client_wait_timeout():
    end_time = datetime.datetime.now() + datetime.timedelta(0, CONSTS.LR_CLIENT_WAIT_TIMEOUT);
    while not tcpClient and datetime.datetime.now() < end_time:
        await asyncio.sleep(0.1)
        
def wait_client(port):
    global tcpClient
    tcpClient = None
    
    loop = asyncio.get_event_loop()
    server = asyncio.start_server(handle_connection, CONSTS.LR_HOST_NAME, port, loop=loop)
    loop.run_until_complete(server)
    loop.run_until_complete(client_wait_timeout())
    
    if tcpClient:
        loop.run_until_complete(tcpClient.set_solution_id())
        
    return tcpClient

if args.replay:
    visio = json.load(gzip.open(args.replay))
    assert(visio.get('visio_version', 0) >= 2)
    start_game = visio['visio_info'][0]
    assert(start_game['type'] == 'start_game')

    CONSTS.SPEED = start_game['speed']
    CONSTS.WIDTH = start_game['width']
    CONSTS.X_CELLS_COUNT = start_game['x_cells_count']
    CONSTS.Y_CELLS_COUNT = start_game['y_cells_count']
    CONSTS.WINDOW_HEIGHT = CONSTS.Y_CELLS_COUNT * CONSTS.WIDTH
    CONSTS.WINDOW_WIDTH = CONSTS.X_CELLS_COUNT * CONSTS.WIDTH

    last_tick = 0
    BONUS_CLASSES = {bc.visio_name: bc for bc in Bonus.__subclasses__()}
    org_send_game_tick = Game.send_game_tick

    def send_game_tick(self: Game):
        global last_tick
        last_tick = self.tick
        try:
            self.bonuses = []
            for b in visio['visio_info'][self.tick]['bonuses']:
                bb = BONUS_CLASSES[b['type']](b['position'])
                bb.active_ticks = b['active_ticks']
                self.bonuses.append(bb)
        except:
            pass
        org_send_game_tick(self)
    Game.send_game_tick = send_game_tick
    Game.game_save = lambda self: None

    class ReplayClient(Client):
        def __init__(self, id):
            self.id = id

        async def get_command(self):
            try:
                direction = visio['visio_info'][last_tick+0]['players'][self.id]['direction']
            except:
                direction = 'left'
            return {"command": direction}

        def get_solution_id(self):
            return visio['config'][self.id]
    clients = [ReplayClient(id) for id in sorted(visio['config'].keys())]

scene = Scene(args.scale, visible=args.console == 'off')

if not args.replay:
    clients = []
    for i in range(1, CONSTS.LR_CLIENTS_MAX_COUNT + 1):
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
        if is_game_over or (args.timeout == 'on' and Runner.game.tick >= CONSTS.MAX_TICK_COUNT):
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

        factScale = max(CONSTS.WINDOW_WIDTH / actual_width, CONSTS.WINDOW_HEIGHT / actual_height)
        xMargin = (actual_width * factScale - CONSTS.WINDOW_WIDTH) / 2
        yMargin = (actual_height * factScale - CONSTS.WINDOW_HEIGHT) / 2
        glOrtho(-xMargin, CONSTS.WINDOW_WIDTH + xMargin, -yMargin, CONSTS.WINDOW_HEIGHT + yMargin, -1, 1)
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
        if args.console == 'off':
            Runner.game = LocalGame(clients, scene, args.timeout == 'on')
        else:
            Runner.game = Game(clients)
        Runner.game.send_game_start()
        pyglet.clock.schedule_interval(Runner.game_loop_wrapper, 1 / 200)


Runner.run_game()

if args.console == 'on':
    scene.window.set_visible(False)

pyglet.app.run()
