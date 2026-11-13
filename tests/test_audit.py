import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bank_check_extraction_claim_audit import phrases
from bank_check_extraction_claim_audit.audit import audit, source_evidence, document_claims
from bank_check_extraction_claim_audit.__main__ import main

EXPECTED_POSITIVE = ('check extraction', 'extract checks', 'extracts checks', 'extracting checks', 'extract check', 'extracts check', 'extracting check', 'check parsing', 'check parser', 'parse checks', 'parses checks', 'parse check', 'parses check', 'bank check extraction', 'extract bank checks', 'extracts bank checks', 'extracting bank checks', 'extract bank check', 'extracts bank check', 'extracting bank check', 'bank check data extraction', 'extract bank check data', 'extracts bank check data', 'extracting bank check data', 'bank check parsing', 'bank check parser', 'parse bank checks', 'parses bank checks', 'parse bank check', 'parses bank check', 'us bank check extraction', 'extract bank check fields', 'cheque extraction', 'extract cheques', 'extracts cheques', 'extracting cheques', 'extract cheque', 'extracts cheque', 'extracting cheque', 'cheque parsing', 'cheque parser', 'micr extraction', 'extract micr', 'extracts micr', 'extracting micr', 'micr line extraction', 'extract micr line', 'extracts micr line', 'extracting micr line', 'micr parsing')
EXPECTED_NEGATIVE = ('no bank check extraction', 'does not extract bank checks', 'does not extract bank check', 'does not support bank check extraction', 'without bank check extraction', 'no check extraction', 'does not extract checks', 'does not extract check', 'does not support check extraction', 'without check extraction', 'no cheque extraction', 'does not extract cheques', 'does not extract cheque', 'does not support cheque extraction', 'no micr extraction', 'does not extract micr', 'does not extract micr line', 'no check parser', 'does not parse checks', 'does not parse check', 'bank check extraction not supported', 'check extraction not supported', 'no bank check parser', 'does not parse bank checks')
EXPECTED_GENERIC = ('extract_bank_check', 'extract_bank_checks', 'parse_bank_check', 'parse_bank_checks', 'extract_check', 'extract_checks', 'parse_check', 'parse_checks', 'extract_check_data', 'check_extraction', 'check_extractor', 'check_parser', 'bank_check_extraction', 'bank_check_extractor', 'extract_micr', 'parse_micr', 'micr_extraction', 'extract_routing_number', 'extract_account_number', 'check_data_extraction', 'cheque_extraction', 'extract_cheque', 'parse_cheque', 'cheque_parser')


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                status = main(list(args))
            except SystemExit as error:
                status = error.code
        return status, out.getvalue(), err.getvalue()

    def test_phrase_oracle(self):
        tree = ast.parse(Path(phrases.__file__).read_text())
        values = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)}
        self.assertEqual(values['BANKCHECKEXTRACTION'], EXPECTED_POSITIVE)
        self.assertEqual(values['NOBANKCHECKEXTRACTION'], EXPECTED_NEGATIVE)
        self.assertEqual(values['GENERIC_NAMES'], EXPECTED_GENERIC)
        self.assertEqual((len(EXPECTED_POSITIVE), len(EXPECTED_NEGATIVE), len(EXPECTED_GENERIC)), (50, 24, 24))
        self.assertEqual(len(set(EXPECTED_GENERIC)), 24)

    def test_good(self):
        self.put('README.md', 'We extract bank checks.')
        self.put('app.py', 'x.extract_bank_check(image)')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')
        self.assertEqual(self.cli('audit', str(self.root))[0], 0)

    def test_bad_exact_high(self):
        self.put('README.md', 'We extract bank checks.')
        self.put('app.py', 'text = page.extract_text()')
        report = audit(self.root)
        self.assertEqual(report['findings'][0]['id'], 'documented-bank-check-extraction-claim-false')
        self.assertEqual(report['findings'][0]['severity'], 'HIGH')
        self.assertEqual(self.cli('audit', str(self.root))[0], 2)

    def test_test_only(self):
        self.put('README.md', 'check extraction')
        self.put('tests/checks.py', 'x.extract_bank_check(image)')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')
        self.assertEqual(self.cli('audit', str(self.root))[0], 0)
        self.assertEqual(self.cli('audit', str(self.root), '--fail-on', 'medium')[0], 2)

    def test_denial_exact(self):
        self.put('README.md', 'does not extract bank checks')
        self.put('app.py', 'x.extract_bank_check(image)')
        report = audit(self.root)
        self.assertEqual(len(report['findings']), 1)
        self.assertEqual(report['findings'][0]['id'], 'documented-no-bank-check-extraction-claim-false')
        self.assertEqual(report['findings'][0]['severity'], 'HIGH')
        self.assertEqual(self.cli('audit', str(self.root))[0], 2)

    def test_no_claim(self):
        self.put('README.md', 'Documentation auditor')
        self.put('app.py', 'x.extract_check(image)')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_no_source_asymmetry(self):
        self.put('README.md', 'check extraction')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')
        self.put('README.md', 'no check extraction')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_fences_and_inline(self):
        for marker in ['```', '~~~', '   ````']:
            self.assertEqual(document_claims(marker + '\ncheck extraction\n' + marker), ([], []))
        self.assertEqual(document_claims('`check extraction`')[0], ['check extraction'])
        self.assertEqual(document_claims('````\ncheck extraction\n```\nextract checks\n````'), ([], []))
        self.assertTrue(document_claims('    ```\ncheck extraction\n    ```')[0])

    def test_normalization_and_paragraphs(self):
        self.assertEqual(document_claims("Doesn't extract bank-checks."), ([], ['does not extract bank checks']))
        self.assertEqual(document_claims('EXTRACT\nBANK CHECKS')[0], ['extract bank checks'])
        self.assertEqual(document_claims('extract\n\nbank checks'), ([], []))
        self.assertEqual(document_claims('recheck extractionist'), ([], []))
        self.assertEqual(document_claims('bank check data extraction')[0], ['bank check data extraction'])

    def test_all_phrases(self):
        for phrase in EXPECTED_POSITIVE:
            with self.subTest(phrase=phrase):
                self.assertEqual(document_claims(phrase), ([phrase], []))
        for phrase in EXPECTED_NEGATIVE:
            with self.subTest(phrase=phrase):
                self.assertEqual(document_claims(phrase), ([], [phrase]))

    def test_single_module_pairs(self):
        self.put('README.md', 'check extraction')
        for client, operation in [
            ('import mindee\nc = mindee.Client()', 'c.parse(BankCheckV1, doc)'),
            ('from veryfi import Client\nc = Client()', 'c.process_check(doc)'),
            ('from azure.ai.formrecognizer import DocumentAnalysisClient\nc = DocumentAnalysisClient()', 'c.begin_analyze_document("prebuilt-check.us", doc)'),
        ]:
            self.put('a.py', client)
            self.put('b.py', operation)
            self.assertEqual(audit(self.root)['verdict'], 'FAIL')

    def test_excluded_paths(self):
        self.put('README.md', 'check extraction')
        for path in ['fixtures/a.py', 'docs/a.py', 'examples/a.py']:
            self.put(path, 'x.extract_check(doc)')
        self.assertEqual(audit(self.root)['test_evidence'], [])
        self.assertEqual(audit(self.root)['production_evidence'], [])
        for path in ['test_a.py', 'a_test.py', 'nested/tests/a.py']:
            self.put(path, 'x.extract_check(doc)')
        self.assertEqual(len(audit(self.root)['test_evidence']), 3)
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')

    def test_symlinks(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other)
            (outside / 'a.py').write_text('x.extract_check(doc)')
            (outside / 'README.md').write_text('check extraction')
            (self.root / 'a.py').symlink_to(outside / 'a.py')
            (self.root / 'README.md').symlink_to(outside / 'README.md')
            (self.root / 'linked').symlink_to(outside, target_is_directory=True)
            self.assertEqual(audit(self.root)['verdict'], 'PASS')
            self.put('docs/claim.md', 'check extraction')
            self.assertEqual(audit(self.root)['production_evidence'], [])
            self.assertEqual(audit(self.root)['verdict'], 'FAIL')

    def test_document_scope(self):
        self.put('other.md', 'check extraction')
        self.put('nested/README.md', 'check extraction')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')
        self.put('nested/docs/page.md', 'check extraction')
        self.assertEqual(audit(self.root)['findings'][0]['docs'], ['nested/docs/page.md'])

    def test_ignore_prefixes(self):
        self.put('README.md', 'check extraction')
        self.put('vendor/a.py', 'x.extract_check(doc)')
        self.put('vendors/b.py', 'x.extract_check(doc)')
        self.assertEqual(audit(self.root, ['vendor'])['production_evidence'], ['vendors/b.py'])
        self.assertEqual(self.cli('audit', str(self.root), '--ignore', 'vendor', '--ignore', 'vendors')[0], 2)
        self.assertEqual(self.cli('audit', str(self.root), '--ignore', 'README.md')[0], 0)

    def test_json_and_verbose(self):
        self.put('README.md', 'check extraction')
        status, out, _ = self.cli('audit', str(self.root), '--json')
        self.assertEqual(status, 2)
        report = json.loads(out)
        self.assertEqual(report['verdict'], 'FAIL')
        self.assertIsInstance(report['findings'][0]['message'], str)
        self.assertEqual(set(report), {'verdict', 'findings', 'production_evidence', 'test_evidence'})
        self.assertIn('README.md', self.cli('audit', str(self.root), '--verbose')[1])

    def test_cli_usage_and_io_errors(self):
        for args in [[], ['oops'], ['audit', '--fail-on', 'MEDIUM'], ['audit', '--ignore'], ['audit', '--unknown'], ['audit', str(self.root / 'absent')], ['audit', str(self.root), '--ignore', '../outside']]:
            with self.subTest(args=args):
                self.assertEqual(self.cli(*args)[0], 1)
        self.put('file', '')
        self.assertEqual(self.cli('audit', str(self.root / 'file'))[0], 1)
        (self.root / 'README.md').write_bytes(b'\xff')
        self.assertEqual(self.cli('audit', str(self.root))[0], 1)

    def test_version_and_entrypoints(self):
        status, out, _ = self.cli('--version')
        self.assertEqual((status, out.strip()), (0, '0.1.0'))
        result = subprocess.run([sys.executable, '-m', 'bank_check_extraction_claim_audit', '--version'], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '0.1.0'))
        metadata = Path(__file__).resolve().parents[1] / 'pyproject.toml'
        if metadata.exists():
            self.assertIn('bank-check-extraction-claim-audit = "bank_check_extraction_claim_audit.__main__:main"', metadata.read_text())

    def test_self_readme(self):
        readme = Path(__file__).resolve().parents[1] / 'README.md'
        if readme.exists():
            self.assertEqual(document_claims(readme.read_text()), ([], []))


def add_source_case(name, source, expected):
    def test(self):
        self.assertEqual(source_evidence(source), expected, source)
    setattr(AuditTests, 'test_source_' + name, test)


M = 'import mindee\nc = mindee.Client()\n'
A = 'from azure.ai.formrecognizer import DocumentAnalysisClient\nc = DocumentAnalysisClient()\n'
V = 'import veryfi\nc = veryfi.Client()\n'
for name, code in {
    'mindee_bank': M + 'c.parse(BankCheckV1, doc)',
    'mindee_type': M + 'c.parse(TypeBankCheckV1, doc)',
    'mindee_product': M + 'c.parse(product.us.BankCheckV1, doc)',
    'mindee_keyword': M + 'c.parse(product=documents.TypeBankCheckV1)',
    'mindee_full_product': M + 'c.parse(mindee.product.us.BankCheckV1, doc)',
    'mindee_from_alias': 'from mindee import Client as MC\nc = MC()\nc.parse(BankCheckV1, doc)',
    'mindee_module_alias': 'import mindee as md\nc = md.Client()\nc.parse(BankCheckV1, doc)',
    'mindee_assignment_alias': 'from mindee import Client\nMC = Client\nc = MC()\nc.parse(BankCheckV1, doc)',
    'mindee_annotated_alias': 'from mindee import Client\nMC: object = Client\nc = MC()\nc.parse(BankCheckV1, doc)',
    'azure_analysis': A + 'c.begin_analyze_document("prebuilt-check.us", doc)',
    'azure_intelligence_url': 'from azure.ai.documentintelligence import DocumentIntelligenceClient\nc = DocumentIntelligenceClient()\nc.begin_analyze_document_from_url("prebuilt-check.us", url)',
    'azure_keyword': A + 'c.begin_analyze_document(model_id="prebuilt-check.us", document=doc)',
    'azure_module': 'import azure.ai.formrecognizer\nc = azure.ai.formrecognizer.DocumentAnalysisClient()\nc.begin_analyze_document("prebuilt-check.us", doc)',
    'azure_module_alias': 'import azure.ai.documentintelligence as az\nc = az.DocumentIntelligenceClient()\nc.begin_analyze_document("prebuilt-check.us", doc)',
    'azure_from_alias': 'from azure.ai.formrecognizer import DocumentAnalysisClient as DAC\nc = DAC()\nc.begin_analyze_document("prebuilt-check.us", doc)',
    'veryfi_from_alias': 'from veryfi import Client as VC\nc = VC()\nc.process_check(doc)',
    'veryfi_module_alias': 'import veryfi as vf\nc = vf.Client()\nc.process_check(doc)',
    'dead_code': 'if False:\n    x.extract_check(doc)',
}.items():
    add_source_case(name, code, True)
for name in ['process_check', 'process_check_url', 'process_check_with_remittance', 'process_check_with_remittance_url']:
    add_source_case('veryfi_' + name, V + 'c.' + name + '(doc)', True)
for name in EXPECTED_GENERIC:
    add_source_case('generic_attribute_' + name, 'x.' + name + '(doc)', True)
    add_source_case('generic_import_' + name, 'from provider import ' + name + ' as operation\noperation(doc)', True)
    add_source_case('generic_bare_' + name, name + '(doc)', False)
    add_source_case('generic_shadow_' + name, 'def ' + name + '(doc): pass\nx.' + name + '(doc)', False)
for name, code in {
    'bare_mindee': 'import mindee', 'bare_veryfi': 'import veryfi',
    'bare_azure': 'import azure.ai.formrecognizer', 'bare_boto': 'import boto3',
    'mindee_client': M, 'azure_client': A, 'veryfi_client': V,
    'mindee_no_client': 'import mindee\nc.parse(BankCheckV1, doc)',
    'veryfi_no_client': 'import veryfi\nc.process_check(doc)',
    'azure_no_client': 'import azure.ai.formrecognizer\nc.begin_analyze_document("prebuilt-check.us", doc)',
    'mindee_no_import': 'c = mindee.Client()\nc.parse(BankCheckV1, doc)',
    'veryfi_no_import': 'c = veryfi.Client()\nc.process_check(doc)',
    'azure_dynamic_model': A + 'c.begin_analyze_document(model_id=model)',
    'azure_wrong_argument': A + 'c.begin_analyze_document(doc, "prebuilt-check.us")',
    'invalid': 'x.extract_check(\n', 'comment': '# x.extract_check(doc)',
    'string': '"x.extract_check(doc)"', 'reference': 'x.extract_check',
    'micr_string': 'from micr import Parser\nParser(line).parse()',
    'regex': 'import re\ntext = page.extract_text()\nfields = {"amount": re.search("amount", text)}',
    'subprocess_mindee': 'import subprocess\nsubprocess.run(["mindee", "parse", "check.png"])',
    'subprocess_veryfi': 'import subprocess\nsubprocess.run(["veryfi", "process-check", "check.png"])',
    'shadow_function': 'from library import extract_check\ndef extract_check(doc): pass\nextract_check(doc)',
    'shadow_method': 'class Wrapper:\n    def extract_check(self, doc): pass\nx.extract_check(doc)',
    'shadow_class': 'from library import extract_check\nclass extract_check: pass\nextract_check(doc)',
    'shadow_alias_target': 'from library import extract_check as op\ndef extract_check(doc): pass\nop(doc)',
    'shadow_mindee_client': M + 'class Client: pass\nc.parse(BankCheckV1, doc)',
    'shadow_parse': M + 'def parse(doc): pass\nc.parse(BankCheckV1, doc)',
    'shadow_veryfi_operation': V + 'def process_check(doc): pass\nc.process_check(doc)',
    'bound_assign': 'from library import extract_check\nextract_check = unrelated\nextract_check(doc)',
    'bound_annotated': 'from library import extract_check\nextract_check: object = unrelated\nextract_check(doc)',
    'bound_with': 'from library import extract_check\nwith context() as extract_check:\n    extract_check(doc)',
    'bound_async_with': 'from library import extract_check\nasync def go():\n    async with context() as extract_check:\n        extract_check(doc)',
    'bound_module': M + 'with context() as mindee:\n    mindee.Client()\nc.parse(BankCheckV1, doc)',
}.items():
    add_source_case(name, code, False)
for product in ['InvoiceV4', 'ReceiptV5', 'PassportV1', 'FinancialDocumentV1', 'CustomV1', 'Other']:
    add_source_case('mindee_wrong_' + product, M + 'c.parse(product.' + product + ', doc)', False)
for model in ['prebuilt-invoice', 'prebuilt-receipt', 'prebuilt-layout', 'prebuilt-read', 'prebuilt-idDocument', 'prebuilt-bankStatement', 'prebuilt-check', 'other']:
    add_source_case('azure_wrong_' + model.replace('-', '_'), A + 'c.begin_analyze_document(' + repr(model) + ', doc)', False)
for operation in ['process_document', 'process_document_url', 'process_bank_statement_document', 'classify_document', 'get_check', 'get_checks', 'update_check']:
    add_source_case('veryfi_wrong_' + operation, V + 'c.' + operation + '(doc)', False)
for module, operations in {
    'textract': ['analyze_document', 'analyze_expense', 'start_document_analysis', 'get_expense_analysis'],
    'pdfplumber': ['extract_text', 'extract_table', 'extract_tables', 'find_table', 'find_tables'],
    'fitz': ['extract_text', 'find_tables'], 'pypdf': ['extract_text'], 'PyPDF2': ['extract_text'],
    'pdfminer': ['extract_text'], 'pytesseract': ['image_to_string'],
    'pandas': ['read_csv', 'read_excel'], 'camelot': ['read_pdf'], 'tabula': ['read_pdf', 'convert_into'],
}.items():
    for operation in operations:
        add_source_case('adjacent_' + module + '_' + operation, 'import ' + module + '\n' + module + '.' + operation + '(doc)', False)


add_source_case('mindee_literal_from_gate', 'from mindee import product\nc = mindee.Client()\nc.parse(BankCheckV1, doc)', True)
add_source_case('veryfi_literal_from_gate', 'from veryfi import helper\nc = veryfi.Client()\nc.process_check(doc)', True)
add_source_case('generic_unaliased_module', 'import extract_check\nextract_check(doc)', False)
add_source_case('generic_aliased_module', 'import provider.extract_check as op\nop(doc)', True)
add_source_case('client_alias_shadow', 'from mindee import Client as MC\nclass Client: pass\nc = MC()\nc.parse(BankCheckV1, doc)', False)


if __name__ == '__main__':
    unittest.main()
