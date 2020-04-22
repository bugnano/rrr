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

import shlex
import subprocess
import signal

from pathlib import Path
from string import Template

import urwid

from .debug_print import (debug_print, debug_pprint)


class CmdEdit(urwid.Edit):
	def keypress(self, size, key):
		if key in ('up', 'down'):
			pass
		elif key == 'backspace':
			if self.edit_pos:
				return super().keypress(size, key)
		else:
			return super().keypress(size, key)


class CmdBar(urwid.WidgetWrap):
	def __init__(self, controller, screen):
		self.controller = controller
		self.screen = screen

		self.action = None
		self.leader = ''
		self.file = None

		self.edit = CmdEdit()

		w = urwid.AttrMap(self.edit, 'default')

		super().__init__(w)

		urwid.connect_signal(self.edit, 'change', self.on_change)

	def on_change(self, edit, new_edit_text):
		if self.action == 'filter':
			self.screen.center.focus.filter(new_edit_text)
			self.screen.center.focus.force_focus()

	def reset(self):
		self.edit.set_caption('')
		self.edit.set_edit_text('')
		self.screen.pile.focus_position = 0
		self.screen.center.focus.remove_force_focus()

		self.action = None
		self.leader = ''

	def execute(self):
		if self.action == 'mkdir':
			self.do_mkdir()
		elif self.action == 'rename':
			self.do_rename()
		elif self.action == 'tag_glob':
			self.do_tag_glob()
		elif self.action == 'untag_glob':
			self.do_untag_glob()
		elif self.action == 'shell':
			self.do_shell()

		self.action = None
		self.leader = ''

		self.edit.set_caption('')
		self.edit.set_edit_text('')
		self.screen.pile.focus_position = 0
		self.screen.center.focus.remove_force_focus()

	def set_leader(self, leader):
		self.leader = leader
		self.edit.set_caption(self.leader)

	def prepare_action(self, action, caption, text, edit_pos=-1):
		self.action = action
		self.edit.set_caption(caption)
		self.edit.set_edit_text(text)
		if edit_pos < 0:
			self.edit.set_edit_pos(len(text))
		else:
			self.edit.set_edit_pos(edit_pos)
		self.screen.pile.focus_position = 1
		self.screen.center.focus.force_focus()

	def filter(self):
		self.prepare_action('filter', 'filter: ', self.screen.center.focus.file_filter)

	def mkdir(self, cwd):
		self.file = cwd
		self.prepare_action('mkdir', 'mkdir: ', '')

	def do_mkdir(self):
		new_dir = Path(self.edit.get_edit_text()).expanduser()
		if new_dir.is_absolute():
			new_dir = Path(os.path.normpath(new_dir))
		else:
			new_dir = Path(os.path.normpath(self.file / new_dir))

		try:
			os.makedirs(new_dir, exist_ok=True)
			self.controller.reload(new_dir, only_focused=True)
		except (PermissionError, FileExistsError) as e:
			self.controller.error(f'{e.strerror} ({e.errno})')

	def rename(self, file, mode):
		self.file = file
		text = file.name
		if mode == 'replace':
			text = ''
			edit_pos = -1
		elif mode == 'insert':
			edit_pos = 0
		elif mode == 'append_before':
			edit_pos = len(file.stem)
		elif mode == 'replace_before':
			text = file.suffix
			edit_pos = 0
		else:
			edit_pos = -1

		self.prepare_action('rename', 'rename: ', text, edit_pos)

	def do_rename(self):
		new_name = Path(self.edit.get_edit_text()).expanduser()
		if new_name.is_absolute():
			new_name = Path(os.path.normpath(new_name))
		else:
			new_name = Path(os.path.normpath(self.file.parent / new_name))

		try:
			if new_name.exists():
				if new_name.is_dir():
					if new_name.resolve() == self.file.parent.resolve():
						return

					new_name = new_name / self.file.name
				else:
					if (new_name.parent.resolve() / new_name.name) == (self.file.parent.resolve() / self.file.name):
						return

					self.controller.error(f'File already exists')
					return

			self.file.rename(new_name)
			self.controller.reload(new_name, old_focus=self.file)
		except OSError as e:
			self.controller.error(f'{e.strerror} ({e.errno})')

	def tag_glob(self):
		self.prepare_action('tag_glob', 'tag: ', '*')

	def do_tag_glob(self):
		self.screen.center.focus.tag_glob(self.edit.get_edit_text())

	def untag_glob(self):
		self.prepare_action('untag_glob', 'untag: ', '*')

	def do_untag_glob(self):
		self.screen.center.focus.untag_glob(self.edit.get_edit_text())

	def shell(self):
		self.prepare_action('shell', 'shell: ', '')

	def do_shell(self):
		cwd = str(self.screen.center.focus.cwd)

		try:
			current_file = shlex.quote(str(self.screen.center.focus.get_focus()['file'].relative_to(cwd)))
		except TypeError:
			current_file = shlex.quote('')

		current_tagged = ' '.join([shlex.quote(str(x.relative_to(cwd))) for x in self.screen.center.focus.get_tagged_files()])
		if not current_tagged:
			current_tagged = shlex.quote('')

		if self.screen.center.focus == self.screen.left:
			other = self.screen.right
		else:
			other = self.screen.left

		other_cwd = str(other.cwd)

		try:
			other_file = shlex.quote(str(other.get_focus()['file']))
		except AttributeError:
			other_file = shlex.quote('')

		other_tagged = ' '.join([shlex.quote(str(x)) for x in other.get_tagged_files()])
		if not current_tagged:
			other_tagged = shlex.quote('')

		s = Template(self.edit.get_edit_text())
		d = {
			'f': current_file,
			'd': shlex.quote(cwd),
			's': current_tagged,
			't': current_tagged,
			'F': other_file,
			'D': shlex.quote(other_cwd),
			'S': other_tagged,
			'T': other_tagged,
		}

		self.controller.loop.stop()
		subprocess.run(s.safe_substitute(d), shell=True, cwd=cwd)
		self.controller.loop.start()
		os.kill(os.getpid(), signal.SIGWINCH)
		self.controller.reload()

