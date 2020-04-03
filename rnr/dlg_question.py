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

import urwid

from .tilde_layout import TildeLayout
from .tline_widget import TLineWidget


class DlgQuestion(urwid.WidgetWrap):
	def __init__(self, controller, title, question, on_yes, on_no=None):
		self.controller = controller

		w = urwid.Filler(urwid.Text(f' {question} ', align='center', layout=TildeLayout))
		w = urwid.LineBox(w, title, title_attr='error_title', bline='')
		top = urwid.Padding(w, left=1, right=1)
		self.btn_yes = urwid.AttrMap(urwid.Button('Yes', on_yes), 'error', 'error_focus')
		self.btn_no = urwid.AttrMap(urwid.Button('No', on_no), 'error', 'error_focus')
		w = urwid.Columns([urwid.Divider(' '), (7, self.btn_yes), (2, urwid.Text('  ')), (6, self.btn_no), urwid.Divider(' ')])
		w = urwid.LineBox(urwid.Filler(w), tline='')

		w = urwid.Pile([
			(1, urwid.Filler(urwid.Text(' '))),
			(2, top),
			(1, urwid.Padding(urwid.Filler(TLineWidget(urwid.Text(''))), left=1, right=1)),
			(2, urwid.Padding(w, left=1, right=1)),
			(1, urwid.Filler(urwid.Text(' '))),
		])
		w = urwid.AttrMap(w, 'error')

		super().__init__(w)

	def keypress(self, size, key):
		if key in ('left', 'right', ' ', 'enter'):
			return super().keypress(size, key)
		elif key == 'h':
			return super().keypress(size, 'left')
		elif key == 'l':
			return super().keypress(size, 'right')
		elif key == 'esc':
			self.btn_no.keypress(size, 'enter')

