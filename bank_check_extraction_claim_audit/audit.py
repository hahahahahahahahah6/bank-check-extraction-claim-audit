"""Read-only Markdown and syntax-tree inspection; inspected code is never run."""
import ast
import os
from pathlib import Path
import re

from .phrases import BANKCHECKEXTRACTION, NOBANKCHECKEXTRACTION, GENERIC_NAMES

POSITIVE_ID = 'documented-bank-check-extraction-claim-false'
NEGATIVE_ID = 'documented-no-bank-check-extraction-claim-false'


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def _pattern(phrases):
    return re.compile(r'\b(?:' + '|'.join(re.escape(p) for p in sorted(phrases, key=lambda p: (-len(p), p))) + r')\b')


_POSITIVE = _pattern(BANKCHECKEXTRACTION)
_NEGATIVE = _pattern(NOBANKCHECKEXTRACTION)


def document_claims(text):
    """Return positive and negative matches, excluding fenced code blocks."""
    lines = []
    fence = None
    for line in text.splitlines():
        if fence:
            if re.match(r'^ {0,3}' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*$', line):
                fence = None
            lines.append('')
            continue
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if match and not (match[1][0] == '`' and '`' in match[2]):
            fence = (match[1][0], len(match[1]))
            lines.append('')
        else:
            lines.append(line)
    positive, negative = [], []
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        text = normalize(paragraph)
        negative.extend(m.group() for m in _NEGATIVE.finditer(text))
        text = _NEGATIVE.sub(' ', text)
        positive.extend(m.group() for m in _POSITIVE.finditer(text))
    return positive, negative


def source_evidence(source):
    """Detect listed operations in one module, resolving simple import aliases."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    nodes = list(ast.walk(tree))
    definitions = {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    imports = set()
    bindings = {}
    assignments = {}
    bare_module_imports = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
                if not alias.asname:
                    bare_module_imports.add(alias.name.split('.')[0])
                bindings[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.add(node.module)
            for alias in node.names:
                bindings[alias.asname or alias.name] = node.module + '.' + alias.name
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                        assignments[name.id] = node.value if target is name else None
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars:
                    for name in ast.walk(item.optional_vars):
                        if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store):
                            assignments[name.id] = None

    def resolve(expr, seen=frozenset()):
        if isinstance(expr, ast.Name):
            if expr.id in definitions or expr.id in seen:
                return None
            if expr.id in assignments:
                return resolve(assignments[expr.id], seen | {expr.id})
            return bindings.get(expr.id)
        if isinstance(expr, ast.Attribute):
            base = resolve(expr.value, seen)
            return base + '.' + expr.attr if base else None
        return None

    def gate(module):
        return any(name == module or name.startswith(module + '.') for name in imports)

    def usable_attribute(func):
        return isinstance(func, ast.Attribute) and func.attr not in definitions

    calls = [n for n in nodes if isinstance(n, ast.Call)]
    constructors = {resolve(n.func) for n in calls if not isinstance(n.func, ast.Attribute) or usable_attribute(n.func)}
    constructors = {name for name in constructors if name and name.rsplit('.', 1)[-1] not in definitions}
    # Literal SDK module spellings are also allowed with a from-import gate.
    for call in calls:
        func = call.func
        if usable_attribute(func) and func.attr == 'Client' and isinstance(func.value, ast.Name):
            name = func.value.id
            if name in {'mindee', 'veryfi'} and name not in assignments and name not in definitions and 'Client' not in definitions:
                if name not in bindings or bindings[name] == name:
                    constructors.add(name + '.Client')
    mindee_client = gate('mindee') and 'mindee.Client' in constructors
    veryfi_client = gate('veryfi') and 'veryfi.Client' in constructors
    azure_client = (gate('azure.ai.formrecognizer') or gate('azure.ai.documentintelligence')) and bool(constructors & {
        'azure.ai.formrecognizer.DocumentAnalysisClient',
        'azure.ai.documentintelligence.DocumentIntelligenceClient',
    })
    # The specification also permits a client attribute on an azure-rooted chain.
    if gate('azure.ai.formrecognizer') or gate('azure.ai.documentintelligence'):
        for call in calls:
            func = call.func
            if usable_attribute(func) and func.attr in {'DocumentAnalysisClient', 'DocumentIntelligenceClient'}:
                base = resolve(func.value)
                if base and (base == 'azure' or base.startswith('azure.')):
                    azure_client = True
    for call in calls:
        func = call.func
        if isinstance(func, ast.Name):
            resolved = resolve(func)
            if resolved and func.id not in bare_module_imports and resolved.rsplit('.', 1)[-1] in GENERIC_NAMES and resolved.rsplit('.', 1)[-1] not in definitions:
                return True
        if not usable_attribute(func):
            continue
        name = func.attr
        if name in GENERIC_NAMES:
            return True
        if mindee_client and name == 'parse':
            arguments = list(call.args) + [k.value for k in call.keywords]
            if any((isinstance(arg, ast.Name) and arg.id in {'BankCheckV1', 'TypeBankCheckV1'}) or
                   (isinstance(arg, ast.Attribute) and arg.attr in {'BankCheckV1', 'TypeBankCheckV1'}) for arg in arguments):
                return True
        if azure_client and name in {'begin_analyze_document', 'begin_analyze_document_from_url'}:
            arguments = list(call.args[:1]) + [k.value for k in call.keywords if k.arg == 'model_id']
            if any(isinstance(arg, ast.Constant) and arg.value == 'prebuilt-check.us' for arg in arguments):
                return True
        if veryfi_client and name in {'process_check', 'process_check_url', 'process_check_with_remittance', 'process_check_with_remittance_url'}:
            return True
    return False


def audit(root, ignore=()):
    """Return a JSON-compatible report. Raise OSError for inaccessible inputs."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise OSError('repository must be an existing, non-symlink directory')
    prefixes = []
    for prefix in ignore:
        path = Path(prefix)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('ignore prefixes must be relative paths without ..')
        prefixes.append(path.parts)

    def ignored(parts):
        return any(parts[:len(prefix)] == prefix for prefix in prefixes)

    positive, negative, production, tests = [], [], [], []

    def onerror(error):
        raise error

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        current = Path(directory)
        dirs[:] = sorted(d for d in dirs if not (current / d).is_symlink() and not ignored((current / d).relative_to(root).parts))
        for filename in sorted(files):
            path = current / filename
            relative = path.relative_to(root)
            parts = relative.parts
            if path.is_symlink() or ignored(parts):
                continue
            is_doc = relative.as_posix() == 'README.md' or (path.suffix == '.md' and 'docs' in parts[:-1])
            is_source = path.suffix == '.py' and not {'fixtures', 'docs', 'examples'}.intersection(parts[:-1])
            if not (is_doc or is_source):
                continue
            if is_doc:
                yes, no = document_claims(path.read_text(encoding='utf-8'))
                if yes:
                    positive.append(relative.as_posix())
                if no:
                    negative.append(relative.as_posix())
            if is_source:
                # tokenize.open honors source encoding declarations without executing code.
                import tokenize
                try:
                    with tokenize.open(str(path)) as handle:
                        source = handle.read()
                except (SyntaxError, UnicodeError):
                    continue
                if source_evidence(source):
                    is_test = 'tests' in parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
                    (tests if is_test else production).append(relative.as_posix())
    findings = []
    if positive and not production:
        findings.append({'id': POSITIVE_ID, 'severity': 'MEDIUM' if tests else 'HIGH',
                         'message': 'Documented capability has evidence only in tests.' if tests else 'Documented capability has no production evidence.',
                         'docs': sorted(positive)})
    if negative and production:
        findings.append({'id': NEGATIVE_ID, 'severity': 'HIGH', 'message': 'Documented denial contradicts production evidence.', 'docs': sorted(negative)})
    return {'verdict': 'FAIL' if findings else 'PASS', 'findings': findings,
            'production_evidence': sorted(production), 'test_evidence': sorted(tests)}
