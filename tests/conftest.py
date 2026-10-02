from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from types import SimpleNamespace
import uuid

import httpx
import pytest
from sqlalchemy import MetaData, Table, create_engine, insert


@dataclass(frozen=True)
class Actor:
    id: str
    username: str
    token: str

    @property
    def headers(self):
        return {'Authorization': f'Bearer {self.token}'}


@pytest.fixture(scope='session')
def api():
    with httpx.Client(base_url=os.getenv('CFG_TEST_BASE_URL', 'http://127.0.0.1:8110'), timeout=20, trust_env=False) as client:
        health = client.get('/api/health')
        assert health.status_code == 200, f'Actual backend must be running: {health.text}'
        assert health.json().get('demo_mode') is True, 'Refusing to create QA fixtures outside demo mode'
        yield client


@pytest.fixture(scope='session')
def database(api):
    url = os.getenv('DATABASE_URL', 'postgresql+psycopg://cfg:cfg-local@127.0.0.1:55472/cfg')
    assert url.startswith('postgresql'), 'This suite requires actual PostgreSQL'
    engine = create_engine(url, pool_pre_ping=True)
    metadata = MetaData()

    def table(name):
        return Table(name, metadata, autoload_with=engine, extend_existing=True)

    yield SimpleNamespace(engine=engine, table=table)
    engine.dispose()


@pytest.fixture(scope='session')
def run_id():
    return f'qa-{uuid.uuid4().hex[:12]}'


@pytest.fixture(scope='session')
def qa_project(database, run_id):
    project = dict(id=str(uuid.uuid4()), slug=run_id, name=f'Isolated QA {run_id}',
                   description='Fixtures for independent alpha integration checks',
                   repository_url=f'https://github.com/cfg-alpha-test/{run_id}',
                   language='Python', status='VERIFIED', impact_score=10, readiness_score=80,
                   is_demo=True)
    with database.engine.begin() as connection:
        projects = database.table('projects')
        if 'required_checks' in projects.c:
            project['required_checks'] = []
        connection.execute(insert(projects).values(**project))
    return project


@pytest.fixture
def actors(api, database, run_id):
    demo = api.get('/api/demo/users')
    assert demo.status_code == 200, demo.text
    admin_data = next(user for user in demo.json() if user['role'] == 'operator')
    admin = Actor(admin_data['id'], admin_data['username'], admin_data['token'])
    users = database.table('users')
    prefix = f'{run_id}-{uuid.uuid4().hex[:6]}'

    def create(role, tier='FRONTIER'):
        actor = Actor(str(uuid.uuid4()), f'{prefix}-{uuid.uuid4().hex[:8]}', f'qa-token-{uuid.uuid4().hex}')
        with database.engine.begin() as connection:
            connection.execute(insert(users).values(
                id=actor.id, username=actor.username, role=role,
                token_hash=hashlib.sha256(actor.token.encode()).hexdigest(),
                model_tier=tier, is_demo=True, suspended=False,
                created_at=datetime.now(timezone.utc),
            ))
        return actor

    def scoped_credential(actor, scopes=None):
        """Convert only a newly created QA actor to a real scoped-credential path."""
        from datetime import timedelta
        from sqlalchemy import update
        assert actor.username.startswith(run_id)
        with database.engine.begin() as connection:
            connection.execute(update(users).where(users.c.id == actor.id).values(is_demo=False))
            connection.execute(insert(database.table('api_credentials')).values(
                id=str(uuid.uuid4()), user_id=actor.id,
                token_hash=hashlib.sha256(actor.token.encode()).hexdigest(),
                name='Isolated QA credential', scopes=scopes or ['work:read', 'work:write'],
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                created_at=datetime.now(timezone.utc), kind='access',
            ))
        return actor

    return SimpleNamespace(admin=admin, author=create('contributor'),
                           reviewers=[create('reviewer') for _ in range(5)],
                           basic=create('contributor', 'BASIC'), create=create,
                           scoped_credential=scoped_credential)


@pytest.fixture
def make_task(api, qa_project, actors, run_id):
    def create(**overrides):
        fields = dict(
            id=f'CFG-QA-{uuid.uuid4().hex[:16]}', project_id=qa_project['id'],
            title=f'Isolated {run_id} task', description='Verify the local work lifecycle',
            difficulty='EASY', risk='LOW', required_model_tier='BASIC', estimated_minutes=15,
            acceptance_criteria=['Independent QA lifecycle assertions pass'],
            allowed_paths=['tests/**'], forbidden_paths=['production-secrets/**'],
            verification_commands=['pytest'],
        )
        fields.update(overrides)
        if fields['risk'] == 'NORMAL' and 'required_model_tier' not in overrides:
            fields['required_model_tier'] = 'STRONG'
        if fields['risk'] in ('HIGH', 'CRITICAL') and 'required_model_tier' not in overrides:
            fields['required_model_tier'] = 'FRONTIER'
        response = api.post('/api/tasks', json=fields, headers=actors.admin.headers)
        assert response.status_code == 200, response.text
        result = response.json()
        if fields['project_id'] == qa_project['id']:
            result['_repository_url'] = qa_project['repository_url']
        else:
            project = api.get(f"/api/projects/{fields['project_id']}")
            assert project.status_code == 200, project.text
            result['_repository_url'] = project.json()['repository_url']
        return result

    return create
