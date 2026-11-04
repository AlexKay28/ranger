"""Shared spawn fakes for the harness transport seams.

The sync harness transport spawns through `ranger._engine._Popen`
(`_popen_run`: spawn -> communicate -> kill-tree on timeout/interrupt),
so a fake proc must offer exactly the fields the engine reads off a
finished proc — `.stdout`, `.stderr`, `.returncode`, plus a
`communicate(timeout=...)` that replays the recorded pair. FakePopen
doubles as a CompletedProcess stand-in on the seams that still call
`subprocess.run` (models listing, snapshot/safety git plumbing): those
read the same three fields.
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial

from unittest import mock


def git_sub(cmd) -> str:
    """Git SUBcommand of a argv, skipping an optional `-c key=value`
    prefix (issue #25: parsed git calls now run `git -c
    core.quotepath=false <sub> ...` for literal output bytes)."""
    return cmd[3] if cmd[1:2] == ["-c"] else cmd[1]


class FakePopen:
    """One fake spawned harness proc; communicates its recorded output.

    `communicate` records every timeout it is asked to wait (the new
    per-call timeout seam) and either replays the recorded
    (stdout, stderr) pair or raises `communicate_exc` — the hook for
    faking a timeout or a user interrupt mid-run.
    """

    def __init__(self, stdout="", stderr="", returncode=0, pid=12345,
                 communicate_exc=None):
        self.args = ["fake-harness"]
        self.pid = pid
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.communicate_exc = communicate_exc
        self.communicate_calls = []        # timeouts seen, in call order

    def communicate(self, timeout=None):
        """Replay the recorded pair — or raise, faking timeout/interrupt."""
        self.communicate_calls.append(timeout)
        if self.communicate_exc is not None:
            raise self.communicate_exc
        return self.stdout, self.stderr


class AgentPopenFake:
    """Popen stand-in scripting agent replies through the engine's
    Popen seam, recording every spawn into the SAME ``fake.runs`` log
    a git FakeRunner keeps on the subprocess.run seam — one log, so
    cross-seam ordering/count assertions keep their meaning.
    """

    def __init__(self, fake, cmd, **kw):
        self.args = list(cmd)
        self.pid = 777
        self.returncode = 0
        replies = getattr(fake, "agent_replies", None)
        reply = replies.pop(0) if replies else "ok\n"
        self._pair = (reply, "")
        fake.runs.append(list(cmd))
        if hasattr(fake, "kws"):
            fake.kws.append(kw)

    def communicate(self, timeout=None):
        return self._pair


def harness_and_git(fake, git_seam="ranger.subprocess.run",
                    agent_seam="ranger._engine._Popen"):
    """Patch both spawn seams for one test (#24): git plumbing still
    rides subprocess.run; agent spawns ride the engine's Popen seam."""
    return _both_patches(fake, git_seam, agent_seam)


@contextmanager
def _both_patches(fake, git_seam, agent_seam):
    with mock.patch(git_seam, side_effect=fake), \
         mock.patch(agent_seam, side_effect=partial(AgentPopenFake,
                                                    fake)):
        yield
