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

import time
import stat
import errno
import shutil

from pathlib import Path

from .database import DataBase
from .utils import (AbortedError, SkippedError)
from .debug_print import (debug_print, debug_pprint)

from .fallocate import *


def rnr_copyfile(cur_file, cur_target, file_size, block_size, info, timers, fd, q, ev_skip, ev_suspend, ev_abort):
	with open(cur_file, 'rb') as fh:
		target_fd = os.open(cur_target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_EXCL | os.O_DSYNC, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH)
		try:
			try:
				fallocate(target_fd, FALLOC_FL_KEEP_SIZE, 0, file_size)
			except OSError:
				pass

			while True:
				t1 = time.monotonic()
				ev_suspend.wait()
				t2 = time.monotonic()
				dt = round(t2 - t1)
				timers['cur_start'] += dt
				timers['start'] += dt

				if ev_abort.is_set():
					raise AbortedError()

				if ev_skip.is_set():
					ev_skip.clear()
					raise SkippedError()

				buf = fh.read(block_size)
				if not buf:
					break

				buffer_length = len(buf)
				bytes_written = 0
				while bytes_written < buffer_length:
					bytes_written += os.write(target_fd, buf[bytes_written:])

				info['cur_bytes'] += bytes_written
				info['bytes'] += bytes_written
				now = time.monotonic()
				if (now - timers['last_write']) > 0.04:
					timers['last_write'] = now
					info['cur_time'] = int(round(now - timers['cur_start']))
					info['time'] = int(round(now - timers['start']))
					q.put(info.copy())
					try:
						os.write(fd, b'\n')
					except OSError:
						pass
		finally:
			os.close(target_fd)

def rnr_cpmv(mode, files, cwd, dest, on_conflict, fd, q, ev_skip, ev_suspend, ev_abort, dbfile, job_id):
	if dbfile:
		db = DataBase(dbfile)

	file_list = sorted(files, key=lambda x: x['file'])
	error_list = []
	skipped_list = []
	aborted_list = []
	completed_list = []

	dest = Path(dest)

	try:
		block_size = max(dest.lstat().st_blksize, 131072)
	except (OSError, AttributeError):
		block_size = 131072

	info = {
		'cur_source': '',
		'cur_target': '',
		'cur_size': 0,
		'cur_bytes': 0,
		'cur_time': 0,
		'files': 0,
		'bytes': 0,
		'time': 0,
	}

	timers = {}

	dir_list = []
	rename_dir_stack = []
	skip_dir_stack = []

	if dest.is_dir():
		replace_first_path = False
	else:
		replace_first_path = True

	total_bytes = 0
	timers['start'] = time.monotonic()
	timers['last_write'] = timers['start']
	for i_file, file in enumerate(file_list):
		try:
			timers['cur_start'] = time.monotonic()

			t1 = time.monotonic()
			ev_suspend.wait()
			t2 = time.monotonic()
			dt = round(t2 - t1)
			timers['cur_start'] += dt
			timers['start'] += dt

			if ev_abort.is_set():
				raise AbortedError()

			if ev_skip.is_set():
				ev_skip.clear()
				raise SkippedError()

			cur_file = Path(file['file'])
			rel_file = cur_file.relative_to(cwd)

			if replace_first_path:
				cur_target = dest / os.sep.join(rel_file.parts[1:])
			else:
				cur_target = dest / rel_file

			skip_dir_stack_changed = False
			skip_dir = False
			while skip_dir_stack:
				dir_to_skip = skip_dir_stack[-1]
				if dir_to_skip in cur_file.parents:
					skip_dir = True
					break
				else:
					skip_dir_stack.pop()
					skip_dir_stack_changed = True

			if skip_dir_stack_changed and dbfile:
				db.set_skip_dir_stack(job_id, skip_dir_stack)

			rename_dir_stack_changed = False
			(old_target, new_target) = (None, None)
			while rename_dir_stack:
				(old_target, new_target) = rename_dir_stack[-1]
				if old_target in cur_target.parents:
					cur_target = Path(str(cur_target).replace(str(old_target), str(new_target), 1))
					break
				else:
					rename_dir_stack.pop()
					rename_dir_stack_changed = True

			if rename_dir_stack_changed and dbfile:
				db.set_rename_dir_stack(job_id, rename_dir_stack)

			info['cur_source'] = str(rel_file)
			info['cur_target'] = str(cur_target)
			info['cur_size'] = file['lstat'].st_size
			info['cur_bytes'] = 0

			now = time.monotonic()
			if (now - timers['last_write']) > 0.04:
				timers['last_write'] = now
				info['cur_time'] = int(round(now - timers['cur_start']))
				info['time'] = int(round(now - timers['start']))
				q.put(info.copy())
				try:
					os.write(fd, b'\n')
				except OSError:
					pass

			if skip_dir:
				raise SkippedError('no_log')

			when = ''
			try:
				if dbfile:
					db.set_file_status(file, 'IN_PROGRESS')

				parent_dir = cur_target.resolve().parent

				warning = ''
				target_is_dir = False
				if cur_target.exists():
					target_is_dir = stat.S_ISDIR(cur_target.lstat().st_mode)
					if not (file['is_dir'] and target_is_dir):
						if cur_file.resolve() == cur_target.resolve():
							if (mode == 'mv') or (on_conflict not in ('rename_existing', 'rename_copy')):
								raise SkippedError('Same file')

						if on_conflict == 'overwrite':
							if target_is_dir:
								when = 'rmdir'
								os.rmdir(cur_target)
								warning = f'Overwrite'
							else:
								when = 'remove'
								os.remove(cur_target)
								warning = f'Overwrite'
						elif on_conflict == 'rename_existing':
							i = 0
							name = cur_target.name
							existing_target = cur_target
							while existing_target.exists():
								new_name = f'{name}.rnrsave{i}'
								existing_target = existing_target.parent / new_name
								i += 1

							if cur_file.resolve() == cur_target.resolve():
								cur_file = existing_target

							when = 'rename'
							os.rename(cur_target, existing_target)
							warning = f'Renamed to {existing_target.name}'
						elif on_conflict == 'rename_copy':
							i = 0
							name = cur_target.name
							existing_target = cur_target
							while cur_target.exists():
								new_name = f'{name}.rnrnew{i}'
								cur_target = cur_target.parent / new_name
								i += 1

							warning = f'Renamed to {cur_target.name}'
							if file['is_dir']:
								rename_dir_stack.append((existing_target, cur_target))
								if dbfile:
									db.set_rename_dir_stack(job_id, rename_dir_stack)
						else:
							raise SkippedError('Target exists')

				if (mode == 'mv') and not target_is_dir:
					perform_copy = False
					try:
						os.rename(cur_file, cur_target)
						if file['is_dir']:
							skip_dir_stack.append(cur_file)
							if dbfile:
								db.set_skip_dir_stack(job_id, skip_dir_stack)
					except OSError as e:
						perform_copy = True
				else:
					perform_copy = True

				in_error = False

				if perform_copy:
					if file['is_symlink']:
						when = 'symlink'
						os.symlink(os.readlink(cur_file), cur_target)
					elif file['is_dir']:
						when = 'makedirs'
						os.makedirs(cur_target, exist_ok=True)
						dir_list.append({'file': file, 'cur_file': cur_file, 'cur_target': cur_target})
						if dbfile:
							db.set_dir_list(job_id, dir_list)
					elif file['is_file']:
						when = 'copyfile'
						rnr_copyfile(cur_file, cur_target, file['lstat'].st_size, block_size, info, timers, fd, q, ev_skip, ev_suspend, ev_abort)
					else:
						in_error = True
						message = f'Special file'
						error_list.append({'file': file['file'], 'message': message})
						if dbfile:
							db.set_file_status(file, 'ERROR', message)

					if not in_error:
						if not file['is_dir']:
							try:
								os.lchown(cur_target, file['lstat'].st_uid, file['lstat'].st_gid)
							except OSError as e:
								if e.errno == errno.EPERM:
									try:
										os.lchown(cur_target, -1, file['lstat'].st_gid)
									except OSError as e:
										if e.errno == errno.EPERM:
											pass
										else:
											raise
								else:
									raise

							when = 'copystat'
							shutil.copystat(cur_file, cur_target, follow_symlinks=False)

						when = 'fsync'
						parent_fd = os.open(parent_dir, 0)
						try:
							os.fsync(parent_fd)
						finally:
							os.close(parent_fd)

				if (mode == 'mv') and not file['is_dir']:
					if perform_copy:
						when = 'remove'
						os.remove(cur_file)

					when = 'fsync'
					parent_fd = os.open(cur_file.parent, 0)
					try:
						os.fsync(parent_fd)
					finally:
						os.close(parent_fd)

				if not in_error:
					completed_list.append({'file': file['file'], 'message': warning})
					if dbfile:
						db.set_file_status(file, 'DONE', warning)
			except OSError as e:
				message = f'({when}) {e.strerror} ({e.errno})'
				error_list.append({'file': file['file'], 'message': message})
				if dbfile:
					db.set_file_status(file, 'ERROR', message)
		except AbortedError as e:
			break
		except SkippedError as e:
			if str(e) == 'no_log':
				completed_list.append({'file': file['file'], 'message': ''})
				if dbfile:
					db.set_file_status(file, 'DONE', '')
			else:
				message = str(e)
				skipped_list.append({'file': file['file'], 'message': message})
				if dbfile:
					db.set_file_status(file, 'SKIPPED', message)

		total_bytes += file['lstat'].st_size
		info['bytes'] = total_bytes
		info['files'] += 1

	for entry in reversed(dir_list):
		try:
			timers['cur_start'] = time.monotonic()

			t1 = time.monotonic()
			ev_suspend.wait()
			t2 = time.monotonic()
			dt = round(t2 - t1)
			timers['cur_start'] += dt
			timers['start'] += dt

			if ev_abort.is_set():
				raise AbortedError()

			if ev_skip.is_set():
				ev_skip.clear()
				raise SkippedError()

			file = entry['file']
			cur_target = entry['cur_target']
			cur_file = entry['cur_file']
			rel_file = cur_file.relative_to(cwd)
			info['cur_source'] = str(rel_file)
			info['cur_target'] = str(cur_target)
			info['cur_size'] = file['lstat'].st_size
			info['cur_bytes'] = 0

			now = time.monotonic()
			if (now - timers['last_write']) > 0.04:
				timers['last_write'] = now
				info['cur_time'] = int(round(now - timers['cur_start']))
				info['time'] = int(round(now - timers['start']))
				q.put(info.copy())
				try:
					os.write(fd, b'\n')
				except OSError:
					pass

			when = ''
			try:
				parent_dir = cur_target.resolve().parent

				try:
					os.lchown(cur_target, file['lstat'].st_uid, file['lstat'].st_gid)
				except OSError as e:
					if e.errno == errno.EPERM:
						try:
							os.lchown(cur_target, -1, file['lstat'].st_gid)
						except OSError as e:
							if e.errno == errno.EPERM:
								pass
							else:
								raise
					else:
						raise

				when = 'copystat'
				shutil.copystat(cur_file, cur_target, follow_symlinks=False)

				when = 'fsync'
				parent_fd = os.open(parent_dir, 0)
				try:
					os.fsync(parent_fd)
				finally:
					os.close(parent_fd)

				if mode == 'mv':
					when = 'rmdir'
					os.rmdir(cur_file)

					when = 'fsync'
					parent_fd = os.open(cur_file.parent, 0)
					try:
						os.fsync(parent_fd)
					finally:
						os.close(parent_fd)
			except OSError as e:
				message = f'({when}) {e.strerror} ({e.errno})'
				error_list.append({'file': file['file'], 'message': message})
				if dbfile:
					db.set_file_status(file, 'ERROR', message)
		except AbortedError as e:
			aborted_list.extend([{'file': x['file'], 'message': ''} for x in file_list[i_file:]])
			break
		except SkippedError as e:
			message = str(e)
			skipped_list.append({'file': file['file'], 'message': message})
			if dbfile:
				db.set_file_status(file, 'SKIPPED', message)

	q.put({'result': completed_list, 'error': error_list, 'skipped': skipped_list, 'aborted': aborted_list})
	try:
		os.write(fd, b'\n')
	except OSError:
		pass
	os.close(fd)

