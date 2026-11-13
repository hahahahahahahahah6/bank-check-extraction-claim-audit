# Documentation claim auditor

An offline audit tool comparing documented promises with listed call patterns in Python source. Inspected code is parsed, never imported or executed. The auditor makes no network calls, collects no telemetry, and writes no output files. It has no runtime dependencies.

## Install and run

Requires Python 3.9 or newer.

```sh
python3 -m pip install .
bank-check-extraction-claim-audit --version
bank-check-extraction-claim-audit audit /path/to/project --json
python3 -m bank_check_extraction_claim_audit audit . --verbose
bank-check-extraction-claim-audit audit . --ignore tests --ignore vendor --fail-on medium
python3 -m unittest discover
```

The repository argument defaults to the current directory. Each ignore option takes one relative path prefix; repeat the option for multiple prefixes. Prefixes match whole path components. The failure threshold accepts lowercase `high` (default) or `medium`. Exit codes are 0 below the threshold, 2 for findings at or above it, and 1 for usage or I/O errors. A FAIL report may exit 0 when its findings fall below the threshold. Version output is 0.1.0.

JSON contains verdict, findings, production_evidence, and test_evidence fields. Each finding has id, severity, message, and docs fields. A positive promise without production evidence receives HIGH, or MEDIUM if evidence appears only in tests. A denial contradicted by production evidence receives HIGH. With no source files, a positive promise fails and a denial passes. There is at most one finding for each claim family.

```text
documented-bank-check-extraction-claim-false
documented-no-bank-check-extraction-claim-false
```

## Scope

Documentation includes root README.md and Markdown files with a docs directory component. Backtick and tilde fenced blocks with up to three leading spaces are excluded; inline code counts. Paragraphs split on blank lines. Text is lowercased, contractions expand, hyphens become spaces, and whitespace collapses. Exact phrases match at word boundaries, longest first with alphabetical ties. Listed denial spans are removed before positive matching. The phrase module contains the complete fixed vocabulary.

Source files are parsed with the standard syntax tree parser. Symlinked files and directories are skipped. Source in fixtures, docs, or examples directories supplies no evidence. Source under tests, or named with the conventional test prefix or suffix, counts separately. Syntax-invalid files supply no evidence. Paired operations must appear in one module. Import aliases and simple assignment aliases are resolved. Local functions, methods, and classes shadow matching route names. Assignment, annotated assignment, and context manager bindings are tracked.

The checked routes and arguments are:

```text
mindee: Client + parse(BankCheckV1 / TypeBankCheckV1)
azure.ai.formrecognizer.DocumentAnalysisClient or
 azure.ai.documentintelligence.DocumentIntelligenceClient +
 begin_analyze_document / begin_analyze_document_from_url("prebuilt-check.us")
veryfi: Client + process_check / process_check_url /
 process_check_with_remittance / process_check_with_remittance_url
Generic names: GENERIC_NAMES in phrases.py (24 names)
```

## Limits

Static pattern matching is not semantic judgement. Dead code counts; untraceable alias chains can be missed. Only exact listed phrases match, and denial handling depends on its finite list. Each paired route must occur in one module. Cloud client calls establish neither configured credentials nor successful execution.

```text
Cloud APIs: Mindee, Azure Document Intelligence, Veryfi
```

Some deliberately broad phrases can mean verifying extraction quality, collecting assertions from a fixture list, parsing a health status string, or reading machine readable text already supplied by a user. Those meanings can cause false positives. The tool flags the wording and uses listed source patterns to decide whether evidence exists.

```text
check extraction / extract check / extract checks
check parser / check parsing
micr extraction / extract micr
```

Generic calls can wrap an external binary or parse a number typed by a user. Matching calls count, subject to local definition shadowing. A thin wrapper containing only a direct subprocess call fails because external commands provide no evidence. Parsing an already supplied MICR string alone also supplies no evidence unless it uses a listed generic call. Handwritten regular expressions over OCR text plus manual field assembly are missed because a listed call is required.

```text
extract_check / extract_routing_number / extract_account_number
re.search / re.findall
subprocess: mindee CLI, veryfi CLI, any other external check CLI
```

The generic document operations below are excluded. Receipts, invoices, and bank statements are different document types. The Azure model requires its exact regional suffix; the bare spelling is not a real v4.0 model id. Other models and products are outside this capability. Textract has no operation for the checked document type; generic document and expense operations do not count.

```text
Veryfi process_document / process_document_url: excluded (receipts/invoices)
Veryfi process_bank_statement_document: excluded (bank statements)
Veryfi classify_document / get_check / get_checks / update_check: excluded
Azure begin_analyze_document:
 prebuilt-check.us: counted
 prebuilt-check: excluded (missing .us)
 prebuilt-invoice / prebuilt-receipt / prebuilt-layout / prebuilt-read /
 prebuilt-idDocument / prebuilt-bankStatement: excluded
Mindee parse: InvoiceV4 / ReceiptV5 / PassportV1 /
 FinancialDocumentV1 / CustomV1: excluded
Textract analyze_document / analyze_expense /
 start_document_analysis / get_expense_analysis: excluded
```

Plain text reading, OCR, spreadsheet loading, and table operations alone do not count. Bare imports, strings, comments, bare references, invalid syntax, and paired evidence split between modules do not count. Adjacent document types and verification promises below are outside the phrase lists: verifying authenticity differs from retrieving fields.

```text
pdfplumber / fitz / pypdf / PyPDF2 / pdfminer: extract_text
pytesseract: image_to_string
pandas: read_csv / read_excel
camelot: read_pdf; tabula: read_pdf / convert_into
pdfplumber: extract_table / extract_tables / find_table / find_tables
fitz: find_tables
invoice extraction / extract invoices
receipt extraction / extract receipts
ID document extraction / extract passports / passport extraction
bank statement extraction / extract bank statements
verify check / check fraud detection / signature verification
```

MIT licensed.
