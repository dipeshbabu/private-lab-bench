'use strict';

function classifyLabels({ title = '', body = '', files = [], action, state = 'open' }) {
  const labels = new Set();
  const subject = String(title);
  const plain = subject.replace(/^\[[^\]]+\]:?\s*/, '');
  if (state === 'open' && ['opened', 'reopened'].includes(action)) {
    labels.add('needs-triage');
  }
  if (/^(?:\[bug\]|fix(?:\([^)]*\))?!?:)/i.test(subject)) labels.add('bug');
  if (/^(?:\[feature\]|feat(?:\([^)]*\))?!?:)/i.test(subject)) labels.add('enhancement');
  if (/^(?:\[docs?\]|docs(?:\([^)]*\))?!?:)/i.test(subject)) labels.add('documentation');
  if (/^(?:(?:build|chore)\(deps(?:-[^)]*)?\)|deps):/i.test(subject)) labels.add('dependencies');
  if (/^\[task\/pack\]/i.test(subject) || /\b(?:tdc|matbench|proteingym|integration)\b/i.test(plain)) labels.add('task');
  if (/\b(?:benchmark|pack)\b/i.test(plain)) labels.add('benchmark-pack');
  if (/\b(?:privacy|membership inference|differential privacy)\b/i.test(subject)) labels.add('privacy');
  if (/\b(?:schema|protocol)\b/i.test(subject)) labels.add('schema');
  if (/\b(?:metric|uncertainty|bootstrap|sampling|spearman|auroc|rmse|mae)\b/i.test(subject)) labels.add('metric');
  if (/\b(?:receipt|attestation|manifest)\b/i.test(subject)) labels.add('artifact');
  if (/^[a-z]+(?:\([^)]*\))?!:/i.test(subject) || /^BREAKING[ -]CHANGE:/m.test(String(body))) labels.add('breaking-change');
  for (const file of files) {
    if (typeof file !== 'string') continue;
    if (/^(?:docs\/|README\.md$|CONTRIBUTING\.md$|CHANGELOG\.md$|SECURITY\.md$|GOVERNANCE\.md$|CODE_OF_CONDUCT\.md$|\.github\/ISSUE_TEMPLATE\/)/i.test(file)) labels.add('documentation');
    if (/^tests\//.test(file) || /\.test\.cjs$/.test(file)) labels.add('tests');
    if (/^\.github\/(?:workflows|scripts)\//.test(file)) labels.add('ci');
    if (/^(?:pyproject\.toml|requirements[^/]*\.txt|\.github\/dependabot\.ya?ml|\.pre-commit-config\.yaml|Dockerfile)$/.test(file)) labels.add('dependencies');
    if (/^(?:\.pre-commit-config\.yaml|Dockerfile|\.github\/dependabot\.ya?ml)$/.test(file)) labels.add('ci');
    if (/^privatelabbench\/(?:tasks|integrations)\//.test(file)) labels.add('task');
    if (/^privatelabbench\/eval\//.test(file)) labels.add('metric');
    if (/^privatelabbench\/privacy\//.test(file)) labels.add('privacy');
    if (/^privatelabbench\/(?:protocols\.py|data\/schemas\/)/.test(file)) labels.add('schema');
    if (/^privatelabbench\/(?:reports\/|attestation\.py)/.test(file)) labels.add('artifact');
    if (/^privatelabbench\/data\/benchmark_packs\//.test(file)) labels.add('benchmark-pack');
  }
  return [...labels].sort();
}

async function applyLabels({ github, context, core = { info() {} } }) {
  // Dependabot supplies its configured labels itself, including with read-only tokens.
  if (context.actor === 'dependabot[bot]') return [];
  const raw = context.payload.inputs?.number ?? context.payload.issue?.number ?? context.payload.pull_request?.number;
  const number = Number(raw);
  if (!Number.isSafeInteger(number) || number <= 0) throw new Error('A positive issue number is required');
  const route = { ...context.repo, issue_number: number };
  let item = context.payload.issue ?? context.payload.pull_request;
  if (!item) item = (await github.rest.issues.get(route)).data;
  const isPullRequest = Boolean(context.payload.pull_request ?? item.pull_request);
  let files = [];
  if (isPullRequest) {
    const changes = await github.paginate(github.rest.pulls.listFiles, {
      ...context.repo, pull_number: number, per_page: 100,
    });
    files = changes.map(file => file.filename);
  }
  const labels = classifyLabels({
    title: item.title, body: item.body, files,
    action: context.payload.action, state: item.state,
  });
  const existing = new Set((item.labels ?? []).map(label => typeof label === 'string' ? label : label.name));
  const missing = labels.filter(label => !existing.has(label));
  if (missing.length) await github.rest.issues.addLabels({ ...route, labels: missing });
  core.info('Label decision for #' + number + ': ' + missing.join(', '));
  return missing;
}

module.exports = { classifyLabels, applyLabels };
