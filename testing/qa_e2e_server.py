"""Temporary real API for browser tests, isolated from every hosted environment."""

import os
from pathlib import Path
import signal
import sys

from psycopg.conninfo import conninfo_to_dict


def main():
    url = os.environ.get('TEST_DATABASE_URL', '')
    if not url:
        raise SystemExit('Set TEST_DATABASE_URL to a dedicated local test database.')
    params = conninfo_to_dict(url)
    if params.get('host') not in ('127.0.0.1', 'localhost', '::1') or not params.get('dbname', '').endswith('_test'):
        raise SystemExit('Browser tests require a local database whose name ends in _test.')
    # Do not load a developer's hosted credentials from backend/.env.
    for name in ('SUPABASE_URL', 'SUPABASE_SECRET_KEY', 'SUPABASE_PUBLISHABLE_KEY',
                 'SUPABASE_ANON_KEY', 'SUPABASE_DB_URL'):
        os.environ[name] = ''
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    import app as portal
    from postgres_test_support import PostgresTestCase
    from werkzeug.serving import make_server

    fixture = PostgresTestCase()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        fixture.setUp()
        # This health endpoint exists only in the test process, never in the application.
        @portal.app.get('/_qa_e2e_health')
        def qa_e2e_health():
            return {'status': 'ready'}
        with make_server('127.0.0.1', 5052, portal.app, threaded=True) as server:
            server.serve_forever()
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    main()
