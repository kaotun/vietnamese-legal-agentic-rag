import sys, json, re
sys.stdout.reconfigure(encoding='utf-8')

# Test regex trên văn bản doc_id=1
with open('data/raw/laws/vbpl_sample.jsonl', encoding='utf-8') as f:
    doc = json.loads(f.readline())

md = (doc.get('markdown') or '').strip()
print(f'doc_id={doc["item_id"]}, len={len(md)}')
print()

# Pattern hiện tại
CURRENT = re.compile(
    r'(?:^|\n)((?:Điều|ĐIỀU)\s+\d+[a-z]?[\.:\s])',
    re.MULTILINE
)
matches = list(CURRENT.finditer(md))
print(f'Pattern hiện tại: {len(matches)} matches')

# Pattern mới: thêm dấu - sau dấu chấm
NEW_PATTERN = re.compile(
    r'((?:Điều|ĐIỀU)\s+\d+[a-z]?\s*[\.:])',
    re.MULTILINE
)
matches2 = list(NEW_PATTERN.finditer(md))
print(f'Pattern mới (flexible): {len(matches2)} matches')
for m in matches2:
    print(f'  -> pos={m.start()} | {repr(m.group())}')

print()
print('Đoạn text xung quanh "Điều 1":')
idx = md.find('Điều 1')
print(repr(md[max(0,idx-5):idx+40]))
