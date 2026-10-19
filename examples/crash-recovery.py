#!/usr/bin/env python3
"""Interrupt real CLI processes and recover with independently observed evidence.

Uses only a loopback mock LLM and an owned, socket-gated fixture child. Supported
on Linux (child subreaper) and macOS (kernel process-exit notification). This
verifies crash recovery, not model quality or arbitrary descendant containment.
"""
import argparse
import copy
import ctypes
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import threading
import time
import uuid

KEY = 'crash-demo-local-token'
CHILD = '''import json, os, socket
from pathlib import Path
config = json.loads(Path('gate.json').read_text())
with socket.create_connection(('127.0.0.1', config['port']), timeout=60) as gate:
    with Path('executions.jsonl').open('a') as ledger:
        ledger.write(json.dumps({'pid': os.getpid(), 'event': 'started'}) + '\\n')
    gate.sendall((json.dumps({'pid': os.getpid(), 'nonce': config['nonce']}) + '\\n').encode())
    if gate.recv(1) != b'X':
        raise SystemExit(3)
raise SystemExit(7)
'''


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform.startswith('linux') or sys.platform == 'darwin',
            'This process-exit proof requires Linux or macOS; Windows is not verified.')
    old_subreaper = ctypes.c_int()
    if sys.platform.startswith('linux'):
        libc = ctypes.CDLL(None, use_errno=True)
        require(libc.prctl(37, ctypes.byref(old_subreaper), 0, 0, 0) == 0, 'Unable to read child-reaping state')
        require(libc.prctl(36, 1, 0, 0, 0) == 0, 'Unable to enable owned-child reaping')
    output = args.output.absolute()
    output.mkdir(parents=False, exist_ok=False)
    output = output.resolve()
    project = output / 'project'
    project.mkdir()
    env = dict(os.environ, ZAR_MOCK_API_KEY=KEY, NO_PROXY='127.0.0.1,localhost', no_proxy='127.0.0.1,localhost')
    events = []
    processes = []
    checkpoints = {}
    child_pid = None
    child_reaped = False
    connection = None
    kernel_queue = None
    stalled = threading.Event()
    release_api = threading.Event()
    stall_next = threading.Event()

    def argv(*parts):
        return [sys.executable, '-m', 'zar', *parts, '--project', str(project), '--json']

    def command(*parts, denied=False):
        result = subprocess.run(argv(*parts), env=env, capture_output=True, text=True, timeout=30)
        response = json.loads(result.stdout)
        events.append(dict(command=list(parts), returncode=result.returncode, response=response))
        save(output / 'events.json', events)
        require((result.returncode != 0 and not response['ok']) if denied else
                (result.returncode == 0 and response['ok']), f'Unexpected CLI result: {parts}: {result.stdout} {result.stderr}')
        require(denied or not any(d['severity'] == 'error' for d in response['diagnostics']), 'CLI error diagnostics')
        return response.get('data')

    def launch(*parts):
        # Files avoid pipe inheritance/deadlock when the CLI is killed mid-run.
        stdout = (output / ('process-' + str(len(processes)) + '.stdout')).open('w')
        stderr = (output / ('process-' + str(len(processes)) + '.stderr')).open('w')
        try:
            process = subprocess.Popen(argv(*parts), env=env, stdout=stdout, stderr=stderr)
        finally:
            stdout.close()
            stderr.close()
        processes.append(process)
        return process

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != '/v1/chat/completions' or self.headers.get('Authorization') != 'Bearer ' + KEY:
                self.send_error(400)
                return
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            role = json.loads(payload['messages'][-1]['content'])['role']
            if stall_next.is_set():
                stall_next.clear()
                stalled.set()
                release_api.wait(60)
                return  # Deliberately no provider response for the killed client.
            body = dict(summary='Owned crash fixture', evidence=['train.py'], uncertainties=[])
            body.update({'analysis': dict(missing=[]), 'evaluation': dict(verdict='pass'),
                         'planning': dict(hypothesis='Observe interrupted fixture without retry'),
                         'implementation': dict(changes=[]), 'review': dict(verdict='pass'),
                         'interpretation': dict(decision='discard', reason='Interrupted fixture has no score'),
                         'memory': dict(next_action='stop', lesson='Reconcile observed exit before proceeding',
                                        limitation='Owned process fixture only')}[role])
            raw = json.dumps(dict(choices=[dict(message=dict(content=json.dumps(body)), finish_reason='stop')])).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    gate = socket.socket()
    gate.bind(('127.0.0.1', 0))
    gate.listen(1)
    gate.settimeout(30)
    nonce = uuid.uuid4().hex

    def start():
        return command('research', 'start', '--base-url', f'http://127.0.0.1:{server.server_port}/v1',
                       '--model', 'mock-crash', '--api-key-env', 'ZAR_MOCK_API_KEY', '--goal', 'Verify bounded crash recovery',
                       '--read', 'train.py', '--command', 'train', '--metric-file', 'metric.json',
                       '--metric-key', 'score', '--budget-ref', 'owned-crash-fixture', '--seed', '42', '--mode', 'baseline')

    def snapshot(sid):
        session = command('research', 'status', sid)
        return dict(session=session, experiment=load(project / '.autoresearch/experiments' / (session['experiment_id'] + '.json')))

    try:
        command('init')
        (project / 'train.py').write_text(CHILD, encoding='utf-8')
        save(project / 'gate.json', dict(port=gate.getsockname()[1], nonce=nonce))
        settings = load(project / '.autoresearch/project.json')
        settings.update(name='crash-recovery-fixture', objective='Verify real process interruption',
                        comparison=dict(id='crash-v1', dataset_ref='none-process-fixture', split_ref='none', metric='score',
                                        direction='minimize', evaluation_ref='process-exit-v1', min_delta=0),
                        environment=dict(os='other', runtime='python', device='cpu'),
                        commands=[dict(name='train', argv=[sys.executable, '-B', 'train.py'], cwd='.')],
                        editable_paths=['train.py'], budget=dict(max_experiments=2, max_run_seconds=120))
        save(output / 'project-input.json', settings)
        command('project', 'set', '--file', str(output / 'project-input.json'))
        session = start()
        sid = session['id']
        session = command('research', 'advance', sid, '--send')
        require(session['state'] == 'awaiting_approval', 'Expected execution approval')
        command('research', 'approve', sid, '--token', session['approval_token'])
        process = launch('research', 'run', sid)
        connection, _ = gate.accept()
        connection.settimeout(30)
        message = b''
        while not message.endswith(b'\n'):
            chunk = connection.recv(1024)
            require(chunk and len(message) < 4096, 'Invalid child handshake')
            message += chunk
        hello = json.loads(message)
        require(hello['nonce'] == nonce and type(hello['pid']) is int, 'Unknown child connected')
        child_pid = hello['pid']
        started_at = now()
        if sys.platform == 'darwin':
            kernel_queue = select.kqueue()
            kernel_queue.control([select.kevent(child_pid, filter=select.KQ_FILTER_PROC,
                                               flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                               fflags=select.KQ_NOTE_EXIT)], 0, 0)
        process.kill()
        process.wait(timeout=10)
        require(process.returncode < 0, 'CLI was not forcibly terminated')
        checkpoints['unknown'] = snapshot(sid)
        original = checkpoints['unknown']
        require(original['session']['state'] == 'executing' and original['experiment']['execution']['status'] == 'unknown',
                'Interrupted launch was not preserved as unknown')
        save(output / 'unknown-experiment.json', original['experiment'])
        for parts in [('run',), ('reconcile',), ('recover', '--confirm-stopped')]:
            command('research', parts[0], sid, *parts[1:], denied=True)
        checkpoints['after_denied'] = snapshot(sid)
        require(checkpoints['after_denied'] == original, 'Denied recovery mutated unknown state')
        connection.sendall(b'X')
        connection.close()
        connection = None
        if kernel_queue is not None:
            notifications = kernel_queue.control([], 1, 10)
            require(len(notifications) == 1 and notifications[0].ident == child_pid and
                    notifications[0].fflags & select.KQ_NOTE_EXIT, 'No child exit notification')
            exit_code = None  # macOS NOTE_EXIT proves exit, not a portable wait status.
            method = 'kqueue-note-exit'
            child_reaped = True
        else:
            deadline = time.monotonic() + 10
            while True:
                waited, status = os.waitpid(child_pid, os.WNOHANG)
                if waited:
                    child_reaped = True
                    break
                require(time.monotonic() < deadline, 'Child did not exit')
                threading.Event().wait(.01)
            exit_code = os.waitstatus_to_exitcode(status)
            require(exit_code == 7, 'Unexpected fixture exit status')
            method = 'subreaper-waitpid'
            child_reaped = True
        receipt = dict(cli_pid=process.pid, cli_returncode=process.returncode, child_pid=child_pid,
                       child_exit_verified=True, child_exit_method=method, child_exit_code=exit_code,
                       started_at=started_at, finished_at=now(), observation='Owned fixture released after CLI death; kernel confirmed process exit. No metric produced.')
        save(project / 'recovery-evidence.json', receipt)
        updated = copy.deepcopy(original['experiment'])
        updated['execution'].update(status='interrupted', started_at=started_at, finished_at=receipt['finished_at'], exit_code=exit_code,
                                    note=receipt['observation'])
        save(output / 'without-evidence-input.json', updated)
        command('experiment', 'update', updated['id'], '--file', str(output / 'without-evidence-input.json'), denied=True)
        require(snapshot(sid) == original, 'Evidence-less update mutated unknown state')
        updated['execution']['evidence'].append(dict(kind='file', ref='recovery-evidence.json', locator=None,
            sha256=hashlib.sha256((project / 'recovery-evidence.json').read_bytes()).hexdigest()))
        save(output / 'recovery-input.json', updated)
        command('experiment', 'update', updated['id'], '--file', str(output / 'recovery-input.json'))
        session = command('research', 'reconcile', sid)
        require(session['state'] == 'observed' and session['experiment_id'] == updated['id'], 'Reconcile lost attempted experiment')
        command('research', 'run', sid, denied=True)
        checkpoints['reconciled'] = snapshot(sid)
        session = command('research', 'advance', sid, '--send')
        session = command('research', 'decide', sid, '--token', session['approval_token'])
        session = command('research', 'advance', sid, '--send')
        require(session['state'] == 'complete', 'Interrupted experiment did not complete with discard')
        checkpoints['complete'] = snapshot(sid)

        # A separate real CLI dies during provider wait, before any execution.
        calling = start()
        calling_id = calling['id']
        stall_next.set()
        caller = launch('research', 'advance', calling_id, '--send')
        require(stalled.wait(30), 'Provider was not called')
        caller.kill()
        caller.wait(timeout=10)
        release_api.set()
        checkpoints['calling'] = command('research', 'status', calling_id)
        require(checkpoints['calling']['state'] == 'calling' and checkpoints['calling']['calls'] == 1, 'Lost reserved call')
        command('research', 'advance', calling_id, '--send', denied=True)
        command('research', 'recover', calling_id, denied=True)
        recovered = command('research', 'recover', calling_id, '--confirm-stopped')
        require(recovered['state'] == 'planning' and recovered['calls'] == 1, 'Recovery refunded or retried call')
        command('research', 'advance', calling_id, denied=True)
        require(command('research', 'status', calling_id) == recovered, 'Denied transmission mutated recovered state')
        checkpoints['calling_recovered'] = recovered
        retried = command('research', 'advance', calling_id, '--send')
        require(retried['state'] == 'awaiting_approval' and retried['calls'] == 6, 'Expected explicit five-role retry')
        checkpoints['calling_retried'] = retried
        command('research', 'reject', calling_id)
        logs = [json.loads(line) for line in (project / 'executions.jsonl').read_text().splitlines()]
        require(len(logs) == 1 and logs[0]['pid'] == child_pid, 'Duplicate experiment execution')
        require(not (project / 'metric.json').exists(), 'Interrupted fixture produced a metric')
        check = command('check')
        status = command('status')
        save(output / 'checkpoints.json', checkpoints)
        summary = dict(state='complete', mock_llm=True, execution_count=len(logs), same_experiment_id=True,
                       unknown_preserved=True, child_exit_verified=True, calling_recovered=True,
                       session_id=sid, experiment_id=updated['id'], calling_session_id=calling_id,
                       process_evidence=receipt, check=check, status=status,
                       metrics=command('research', 'metrics', calling_id))
        save(output / 'summary.json', summary)
        print(json.dumps(summary, indent=2))
    finally:
        release_api.set()
        if connection is not None:
            try:
                connection.sendall(b'X')
            except OSError:
                pass
            connection.close()
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
        if child_pid is not None and not child_reaped:
            # Closing the owned gate releases this fixture; never send a signal
            # to a possibly reused orphan PID. Kernel exit events / waitpid are
            # the authority. The fixture also has its own bounded socket wait.
            if kernel_queue is not None:
                require(kernel_queue.control([], 1, 10), 'Fixture cleanup exit unconfirmed')
            elif sys.platform.startswith('linux'):
                deadline = time.monotonic() + 10
                while True:
                    waited, _ = os.waitpid(child_pid, os.WNOHANG)
                    if waited:
                        break
                    require(time.monotonic() < deadline, 'Fixture cleanup exit unconfirmed')
                    threading.Event().wait(.01)
        if kernel_queue is not None:
            kernel_queue.close()
        gate.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if sys.platform.startswith('linux'):
            require(libc.prctl(36, old_subreaper.value, 0, 0, 0) == 0, 'Unable to restore child-reaping state')


if __name__ == '__main__':
    main()
