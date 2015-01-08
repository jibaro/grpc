"""Run a group of subprocesses and then finish."""

import multiprocessing
import random
import subprocess
import sys
import tempfile
import time


_MAX_JOBS = 16 * multiprocessing.cpu_count()


def shuffle_iteratable(it):
  """Return an iterable that randomly walks it"""
  # take a random sampling from the passed in iterable
  # we take an element with probablity 1/p and rapidly increase
  # p as we take elements - this gives us a somewhat random set of values before
  # we've seen all the values, but starts producing values without having to
  # compute ALL of them at once, allowing tests to start a little earlier
  nextit = []
  p = 1
  for val in it:
    if random.randint(0, p) == 0:
      p = min(p*2, 100)
      yield val
    else:
      nextit.append(val)
  # after taking a random sampling, we shuffle the rest of the elements and
  # yield them
  random.shuffle(nextit)
  for val in nextit:
    yield val


_SUCCESS = object()
_FAILURE = object()
_RUNNING = object()
_KILLED = object()


class Job(object):
  """Manages one job."""

  def __init__(self, cmdline):
    self._cmdline = ' '.join(cmdline)
    self._tempfile = tempfile.TemporaryFile()
    self._process = subprocess.Popen(args=cmdline,
                                     stderr=subprocess.STDOUT,
                                     stdout=self._tempfile)
    self._state = _RUNNING
    sys.stdout.write('\x1b[0G\x1b[2K\x1b[33mSTART\x1b[0m: %s' %
                     self._cmdline)
    sys.stdout.flush()

  def state(self):
    """Poll current state of the job. Prints messages at completion."""
    if self._state == _RUNNING and self._process.poll() is not None:
      if self._process.returncode != 0:
        self._state = _FAILURE
        self._tempfile.seek(0)
        stdout = self._tempfile.read()
        sys.stdout.write('\x1b[0G\x1b[2K\x1b[31mFAILED\x1b[0m: %s'
                         ' [ret=%d]\n'
                         '%s\n' % (
                             self._cmdline, self._process.returncode, stdout))
        sys.stdout.flush()
      else:
        self._state = _SUCCESS
        sys.stdout.write('\x1b[0G\x1b[2K\x1b[32mPASSED\x1b[0m: %s' %
                         self._cmdline)
        sys.stdout.flush()
    return self._state

  def kill(self):
    if self._state == _RUNNING:
      self._state = _KILLED
      self._process.terminate()


class Jobset(object):
  """Manages one run of jobs."""

  def __init__(self, check_cancelled):
    self._running = set()
    self._check_cancelled = check_cancelled
    self._cancelled = False
    self._failures = 0

  def start(self, cmdline):
    """Start a job. Return True on success, False on failure."""
    while len(self._running) >= _MAX_JOBS:
      if self.cancelled(): return False
      self.reap()
    if self.cancelled(): return False
    self._running.add(Job(cmdline))
    return True

  def reap(self):
    """Collect the dead jobs."""
    while self._running:
      dead = set()
      for job in self._running:
        st = job.state()
        if st == _RUNNING: continue
        if st == _FAILURE: self._failures += 1
        dead.add(job)
      for job in dead:
        self._running.remove(job)
      if not dead: return
      time.sleep(0.1)

  def cancelled(self):
    """Poll for cancellation."""
    if self._cancelled: return True
    if not self._check_cancelled(): return False
    for job in self._running:
      job.kill()
    self._cancelled = True
    return True

  def finish(self):
    while self._running:
      if self.cancelled(): pass  # poll cancellation
      self.reap()
    return not self.cancelled() and self._failures == 0


def _never_cancelled():
  return False


def run(cmdlines, check_cancelled=_never_cancelled):
  js = Jobset(check_cancelled)
  for cmdline in shuffle_iteratable(cmdlines):
    if not js.start(cmdline):
      break
  return js.finish()
