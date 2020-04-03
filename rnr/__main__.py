#! /usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (C) 2020  Franco Bugnano
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import sys
import os

import argparse
import shutil
import stat

from pathlib import Path

import urwid

import xdg.BaseDirectory

CONFIG_DIR = Path(xdg.BaseDirectory.save_config_path('rnr'))

sys.path.insert(0, str(CONFIG_DIR))
_dont_write_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True

from .config import *

try:
	from config import *
except ModuleNotFoundError:
	try:
		shutil.copy(Path(__file__).parent / 'config.py', CONFIG_DIR)
		print(sys.path)
		from config import *
	except (ModuleNotFoundError, FileNotFoundError, PermissionError, IsADirectoryError):
		pass

sys.dont_write_bytecode = _dont_write_bytecode
del _dont_write_bytecode
sys.path.pop(0)

from . import __version__

from .panel import Panel
from .cmdbar import CmdBar
from .buttonbar import ButtonBar
from .bookmarks import (Bookmarks, BOOKMARK_KEYS)
from .dlg_error import (DlgError)
from .dlg_question import (DlgQuestion)
from .debug_print import (debug_print, set_debug_fh)


PALETTE = [
	('default', 'default', 'default'),

	('panel', PANEL_FG, PANEL_BG),
	('reverse', REVERSE_FG, REVERSE_BG),
	('selected', SELECTED_FG, SELECTED_BG),
	('marked', MARKED_FG, PANEL_BG),
	('markselect', MARKSELECT_FG, SELECTED_BG),

	('directory', DIRECTORY_FG, PANEL_BG),
	('dir_symlink', DIR_SYMLINK_FG, PANEL_BG),
	('executable', EXECUTABLE_FG, PANEL_BG),
	('symlink', SYMLINK_FG, PANEL_BG),
	('stalelink', STALELINK_FG, PANEL_BG),
	('device', DEVICE_FG, PANEL_BG),
	('special', SPECIAL_FG, PANEL_BG),
	('archive', ARCHIVE_FG, PANEL_BG),

	('hotkey', HOTKEY_FG, HOTKEY_BG),

	('error', ERROR_FG, ERROR_BG),
	('error_title', ERROR_TITLE_FG, ERROR_BG),
	('error_focus', ERROR_FOCUS_FG, ERROR_FOCUS_BG),
]


class Screen(urwid.WidgetWrap):
	def __init__(self, controller):
		self.left = Panel(controller)
		self.right = Panel(controller)
		self.center = urwid.Columns([self.left, self.right])
		self.command_bar = CmdBar(controller, self)
		w = urwid.Filler(self.command_bar)
		pile_widgets = [self.center, (1, w)]

		if SHOW_BUTTONBAR:
			bottom = ButtonBar()
			w = urwid.Filler(bottom)
			pile_widgets.append((1, w))

		self.pile = urwid.Pile(pile_widgets)
		self.pile.focus_position = 0
		self.update_focus()

		super().__init__(self.pile)

	def update_focus(self):
		for i, e in enumerate(self.center.contents):
			if i == self.center.focus_position:
				e[0].set_title_attr('reverse')
			else:
				e[0].set_title_attr('panel')


class App(object):
	def __init__(self, printwd):
		self.printwd = printwd

		self.opener = OPENER
		self.pager = PAGER
		self.editor = EDITOR

		self.screen = Screen(self)
		self.leader = ''

		self.bookmarks = Bookmarks(CONFIG_DIR / 'bookmarks')
		if 'h' not in self.bookmarks:
			self.bookmarks['h'] = Path.home()

	def run(self):
		self.loop = urwid.MainLoop(self.screen, PALETTE, unhandled_input=self.keypress)
		self.loop.run()

	def keypress(self, key):
		if key == 'esc':
			self.screen.command_bar.reset()
			self.leader = ''
		elif self.leader == 's':
			if key == 'n':
				self.screen.left.sort('sort_by_name')
				self.screen.right.sort('sort_by_name')
			elif key == 'N':
				self.screen.left.sort('sort_by_name', reverse=True)
				self.screen.right.sort('sort_by_name', reverse=True)
			elif key == 'e':
				self.screen.left.sort('sort_by_extension')
				self.screen.right.sort('sort_by_extension')
			elif key == 'E':
				self.screen.left.sort('sort_by_extension', reverse=True)
				self.screen.right.sort('sort_by_extension', reverse=True)
			elif key == 'd':
				self.screen.left.sort('sort_by_date')
				self.screen.right.sort('sort_by_date')
			elif key == 'D':
				self.screen.left.sort('sort_by_date', reverse=True)
				self.screen.right.sort('sort_by_date', reverse=True)
			elif key == 's':
				self.screen.left.sort('sort_by_size')
				self.screen.right.sort('sort_by_size')
			elif key == 'S':
				self.screen.left.sort('sort_by_size', reverse=True)
				self.screen.right.sort('sort_by_size', reverse=True)

			self.screen.command_bar.reset()
			self.leader = ''
		elif self.leader == 'm':
			if key in BOOKMARK_KEYS:
				self.bookmarks[key] = self.screen.center.focus.cwd

			self.screen.command_bar.reset()
			self.leader = ''
		elif self.leader in ('`', "'"):
			if key in ('`', "'"):
				if self.screen.center.focus.old_cwd != self.screen.center.focus.cwd:
					self.screen.center.focus.chdir(self.screen.center.focus.old_cwd)
			elif key in BOOKMARK_KEYS:
				try:
					if self.bookmarks[key] != str(self.screen.center.focus.cwd):
						self.screen.center.focus.chdir(Path(self.bookmarks[key]))
				except KeyError:
					pass

			self.screen.command_bar.reset()
			self.leader = ''
		elif self.leader == 'u':
			if key == 'v':
				self.screen.center.focus.untag_all()

			self.screen.command_bar.reset()
			self.leader = ''
		else:
			if key in ('q', 'Q', 'f10'):
				if self.printwd:
					try:
						with open(self.printwd, 'w') as fh:
							fh.write(str(self.screen.center.focus.cwd))
					except (FileNotFoundError, PermissionError):
						pass

				raise urwid.ExitMainLoop()
			elif key == 'tab':
				if self.screen.pile.focus_position == 0:
					self.screen.center.focus_position ^= 1
					self.screen.update_focus()
			elif key in ('f', '/'):
				self.screen.command_bar.filter()
			elif key == 'enter':
				self.screen.command_bar.execute()
			elif key == 'backspace':
				self.screen.left.toggle_hidden()
				self.screen.right.toggle_hidden()
			elif key == 's':
				self.leader = key
				self.screen.command_bar.set_leader(self.leader)
			elif key == 'm':
				self.leader = key
				self.screen.command_bar.set_leader(self.leader)
			elif key in ('`', "'"):
				self.leader = key
				self.screen.command_bar.set_leader(self.leader)
			elif key == 'u':
				self.leader = key
				self.screen.command_bar.set_leader(self.leader)
			elif key == 'meta i':
				cwd = self.screen.center.focus.cwd

				if (self.screen.left is not self.screen.center.focus) and (self.screen.left.cwd != cwd):
					self.screen.left.chdir(cwd)

				if (self.screen.right is not self.screen.center.focus) and (self.screen.right.cwd != cwd):
					self.screen.right.chdir(cwd)
			elif key == 'meta o':
				cwd = self.screen.center.focus.cwd.parent
				obj = self.screen.center.focus.get_focus()
				try:
					if stat.S_ISDIR(obj['stat'].st_mode):
						cwd = obj['file']
				except TypeError:
					pass

				if (self.screen.left is not self.screen.center.focus) and (self.screen.left.cwd != cwd):
					self.screen.left.chdir(cwd)

				if (self.screen.right is not self.screen.center.focus) and (self.screen.right.cwd != cwd):
					self.screen.right.chdir(cwd)
			elif key == 'ctrl r':
				self.reload()
			elif key == 'f7':
				self.screen.command_bar.mkdir(self.screen.center.focus.cwd)
			elif key in ('r', 'c'):
				obj = self.screen.center.focus.get_focus()
				try:
					self.screen.command_bar.rename(obj['file'], mode='replace')
				except TypeError:
					pass
			elif key in ('i', 'I'):
				obj = self.screen.center.focus.get_focus()
				try:
					self.screen.command_bar.rename(obj['file'], mode='insert')
				except TypeError:
					pass
			elif key == 'a':
				obj = self.screen.center.focus.get_focus()
				try:
					self.screen.command_bar.rename(obj['file'], mode='append_before')
				except TypeError:
					pass
			elif key == 'A':
				obj = self.screen.center.focus.get_focus()
				try:
					self.screen.command_bar.rename(obj['file'], mode='append_after')
				except TypeError:
					pass
			elif key == '+':
				self.screen.command_bar.tag_glob()
			elif key in ('-', '\\'):
				self.screen.command_bar.untag_glob()
			elif key == 'f8':
				tagged_files = self.screen.center.focus.get_tagged_files()
				if tagged_files:
					if len(tagged_files) == 1:
						question = f'Delete {tagged_files[0].name}?'
					else:
						question = f'Delete {len(tagged_files)} files/directories?'

					self.screen.center.focus.force_focus()
					self.screen.pile.contents[0] = (urwid.Overlay(DlgQuestion(self, title='Delete', question=question,
						on_yes=lambda x: self.on_delete(tagged_files), on_no=lambda x: self.close_dialog()), self.screen.center,
						'center', max(len(question) + 6, 21),
						'middle', 'pack',
					), self.screen.pile.options())

	def reload(self, focus_path=None, old_focus=None):
		if old_focus is None:
			left_path = focus_path
			right_path = focus_path
		else:
			obj = self.screen.left.get_focus()
			left_path = None
			try:
				if obj['file'] == old_focus:
					left_path = focus_path
			except TypeError:
				pass

			obj = self.screen.right.get_focus()
			right_path = None
			try:
				if obj['file'] == old_focus:
					right_path = focus_path
			except TypeError:
				pass

		self.screen.left.reload(left_path)
		self.screen.right.reload(right_path)

	def error(self, e):
		self.screen.center.focus.force_focus()
		self.screen.pile.contents[0] = (urwid.Overlay(DlgError(self, e), self.screen.center,
			'center', len(e) + 6,
			'middle', 'pack',
		), self.screen.pile.options())

	def close_dialog(self):
		self.screen.pile.contents[0] = (self.screen.center, self.screen.pile.options())
		self.screen.center.focus.remove_force_focus()

	def on_delete(self, files):
		self.close_dialog()


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('-V', '--version', action='version', version=f'%(prog)s {__version__}')
	parser.add_argument('-P', '--printwd', help='Print last working directory to specified file', metavar='<file>')
	parser.add_argument('-d', '--debug', help='activate debug mode', action='store_true')
	args = parser.parse_args()

	if args.debug:
		set_debug_fh(open(Path.home() / 'rnr.log', 'w', buffering=1))

	app = App(args.printwd)
	app.run()


if __name__ == '__main__':
	sys.exit(main())

