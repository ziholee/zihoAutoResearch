"""Loopback HTTP plus real programs: original baseline then improved candidate."""
import json
import io
from contextlib import redirect_stdout,redirect_stderr
import os
import sys
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch
from tests import test_next as fixture
from zar import research,cli
from zar.codec import dumps,loads

class BaselineHTTPTests(unittest.TestCase):
    def test_baseline_then_candidate_preserves_metrics_and_provenance(self):
        h=fixture.NextTests();h.setUp();self.addCleanup(h.doCleanups)
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                context=json.loads(payload['messages'][-1]['content']);requests.append(context)
                answer=h.respond(None,payload['messages']);body=loads(answer['content'])
                if context['role']=='implementation' and context['experiment_mode']=='candidate':
                    code='from pathlib import Path\nPath('+repr(context['metric_file'])+').write_text(\'{"score":0.25}\')\n'
                    body['changes']=[dict(path='train.py',before_sha256=context['sources']['train.py']['sha256'],content=code)]
                raw=json.dumps(dict(choices=[dict(message=dict(role='assistant',content=dumps(body)),finish_reason='stop')])).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        h.profile['base_url']=f'http://127.0.0.1:{server.server_port}/v1'
        def finish(s):
            s=research.advance(h.root,s['id'],send=True);self.assertEqual(s['state'],'awaiting_approval')
            research.approve(h.root,s['id'],s['approval_token']);research.run_session(h.root,s['id'])
            s=research.advance(h.root,s['id'],send=True);research.decide(h.root,s['id'],s['approval_token'],select=True)
            return research.advance(h.root,s['id'],send=True)
        with patch.dict(os.environ,{'ZAR_TEST_KEY':'local-fixture','NO_PROXY':'127.0.0.1','no_proxy':'127.0.0.1'}):
            base=finish(h.start());self.assertEqual((h.root/'train.py').read_text(),h.code)
            parent_bytes=research.session_path(h.root,base['id']).read_bytes()
            out,err=io.StringIO(),io.StringIO();seen=set()
            class Terminal(io.StringIO):
                def isatty(self):return True
                def readline(self):
                    key=err.getvalue().splitlines()[-1].split(':',1)[0]
                    if key in seen:raise AssertionError('Unexpected repeated prompt: '+key)
                    seen.add(key)
                    return {'save':'yes','send':'no'}.get(key,'')+'\n'
            with patch('sys.stdin',Terminal()),redirect_stdout(out),redirect_stderr(err):
                code=cli.main(['research','next',base['id'],'--project',str(h.root),'--json'])
            self.assertEqual(code,0,out.getvalue()+err.getvalue())
            child=loads(out.getvalue())['data']['session'];self.assertEqual(child['calls'],0)
            self.assertNotIn('local-fixture',out.getvalue()+err.getvalue())
            self.assertEqual((h.root/'train.py').read_text(),h.code)
            child=finish(child)
        records=research.context(h.root,child,'memory')
        self.assertEqual(records['comparison']['improvement'],.25)
        self.assertEqual(records['observation']['baseline_id'],base['experiment_id'])
        self.assertEqual(records['observation']['kind'],'performance')
        self.assertEqual(loads((h.root/'metric.json').read_text())['score'],.5)
        self.assertEqual(loads((h.root/child['metric_file']).read_text())['score'],.25)
        self.assertEqual(parent_bytes,research.session_path(h.root,base['id']).read_bytes())
        self.assertEqual(len(requests),14)
        self.assertEqual(requests[7]['next_context']['experiment']['execution']['score'],.5)
        self.assertEqual(requests[7]['outputs'],{})
