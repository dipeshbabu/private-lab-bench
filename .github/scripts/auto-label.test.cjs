'use strict';

const assert = require('node:assert/strict');
const { test } = require('node:test');
const { classifyLabels, applyLabels } = require('./auto-label.cjs');

test('new issue types get concrete labels and enter triage', () => {
  assert.deepEqual(classifyLabels({ title: '[Bug]: CSV error', action: 'opened' }), ['bug', 'needs-triage']);
  assert.deepEqual(classifyLabels({ title: '[Feature]: add protocol checks', action: 'opened' }), ['enhancement', 'needs-triage', 'schema']);
  assert.deepEqual(classifyLabels({ title: '[Task/Pack]: RNA integration', action: 'opened' }), ['needs-triage', 'task']);
  assert.deepEqual(classifyLabels({ title: '[Privacy]: audit method', action: 'opened' }), ['needs-triage', 'privacy']);
});

test('file labels cover scientific code, documentation, tests and dependency tooling', () => {
  const labels = classifyLabels({
    title: 'chore(deps): update tools', action: 'opened', files: [
      'README.md', 'tests/test_runner.py', '.github/workflows/ci.yml',
      'privatelabbench/privacy/release.py', 'privatelabbench/data/schemas/report.json',
      'privatelabbench/integrations/tdc.py', 'privatelabbench/eval/metrics.py',
      'privatelabbench/reports/receipt.py', 'privatelabbench/data/benchmark_packs/demo/pack.yaml',
    ],
  });
  assert.deepEqual(labels, ['artifact', 'benchmark-pack', 'ci', 'dependencies', 'documentation', 'metric', 'needs-triage', 'privacy', 'schema', 'task', 'tests']);
});

test('triage decisions are preserved on edits and explicit breaking changes are recognized', () => {
  assert.deepEqual(classifyLabels({ title: 'fix!: revised protocol', action: 'edited' }), ['breaking-change', 'bug', 'schema']);
  assert.deepEqual(classifyLabels({ title: 'feat: response', body: 'BREAKING CHANGE: altered behavior', action: 'edited' }), ['breaking-change', 'enhancement']);
  assert.deepEqual(classifyLabels({ title: 'ordinary title', action: 'reopened', state: 'closed' }), []);
});

function fixture({ item, files = [], dispatch = false, actor = 'contributor', action = 'opened' }) {
  const calls = [];
  const listFiles = function listFiles() {};
  const github = {
    rest: {
      issues: {
        get: async route => { calls.push(['get', route]); return { data: item }; },
        addLabels: async route => { calls.push(['add', route]); return { data: [] }; },
      },
      pulls: { listFiles },
    },
    paginate: async (method, route) => {
      assert.equal(method, listFiles);
      calls.push(['files', route]);
      return files.map(filename => ({ filename }));
    },
  };
  const context = {
    actor, repo: { owner: 'owner', repo: 'repository' },
    payload: dispatch ? { inputs: { number: String(item.number) } } : {
      action, [item.pull_request ? 'pull_request' : 'issue']: item,
    },
  };
  return { github, context, calls };
}

test('fork PRs use paginated metadata from the base repository', async () => {
  const item = { number: 12, title: 'change', state: 'open', labels: [], pull_request: {}, head: { repo: { full_name: 'untrusted/fork' } } };
  const files = [...Array.from({ length: 125 }, (_, n) => 'other/file-' + n), 'privatelabbench/privacy/release.py'];
  const value = fixture({ item, files });
  assert.deepEqual(await applyLabels(value), ['needs-triage', 'privacy']);
  assert.deepEqual(value.calls[0], ['files', { owner: 'owner', repo: 'repository', pull_number: 12, per_page: 100 }]);
  assert.deepEqual(value.calls[1], ['add', { owner: 'owner', repo: 'repository', issue_number: 12, labels: ['needs-triage', 'privacy'] }]);
});

test('existing labels are preserved and repeat runs avoid writes', async () => {
  const item = { number: 13, title: '[Bug]: error', state: 'open', labels: [{ name: 'bug' }, { name: 'needs-triage' }, { name: 'maintainer-choice' }] };
  const before = JSON.stringify(item);
  const value = fixture({ item });
  assert.deepEqual(await applyLabels(value), []);
  assert.deepEqual(value.calls, []);
  assert.equal(JSON.stringify(item), before);
});

test('dispatch labels a selected closed PR without adding triage', async () => {
  const item = { number: 14, title: 'docs: instructions', state: 'closed', labels: [], pull_request: {} };
  const value = fixture({ item, files: ['README.md'], dispatch: true });
  assert.deepEqual(await applyLabels(value), ['documentation']);
  assert.equal(value.calls[0][0], 'get');
  assert.equal(value.calls.at(-1)[1].issue_number, 14);
});

test('untrusted title and body remain data and are absent from logs', async () => {
  const item = { number: 15, title: '$(throw new Error("unsafe"))', body: '${{ secrets.GITHUB_TOKEN }}', state: 'open', labels: [] };
  const value = fixture({ item });
  const messages = [];
  await applyLabels({ ...value, core: { info: message => messages.push(message) } });
  assert.deepEqual(value.calls[0][1].labels, ['needs-triage']);
  assert.ok(messages.every(message => !message.includes(item.title) && !message.includes(item.body)));
});

test('invalid dispatch identifiers are rejected before an API call', async () => {
  for (const number of ['1; unsafe()', '-1', '2.5', '9007199254740993']) {
    await assert.rejects(applyLabels({ github: {}, context: { actor: 'maintainer', payload: { inputs: { number } } } }), /positive issue number/);
  }
});

test('Dependabot uses its native configured labels without write-token requirements', async () => {
  assert.deepEqual(await applyLabels({ github: {}, context: { actor: 'dependabot[bot]' } }), []);
});
