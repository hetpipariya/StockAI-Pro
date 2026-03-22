import os
import glob

src_dir = r"e:\Projects\stockai-pro\frontend\src"

target1 = """const _rawApi = import.meta.env.VITE_API_URL || "";
const _cleanApi = _rawApi.replace(/\/\+$/, "");
const API_BASE = _cleanApi ? `${_cleanApi}/api/v1` : "/api/v1";"""

target2 = """const _rawApi = import.meta.env.VITE_API_URL || "";
const _cleanApi = _rawApi.replace(/\/$/, "");
const API_BASE = _cleanApi ? `${_cleanApi}/api/v1` : "/api/v1";"""

# Notice in useTradingEngine it was updated to `/\/+$/`
target3 = """const _rawApi = import.meta.env.VITE_API_URL || "";
const _cleanApi = _rawApi.replace(/\/+$/, "");
const API_BASE = _cleanApi ? `${_cleanApi}/api/v1` : "/api/v1";"""

replacement = 'const API_BASE = (import.meta.env.VITE_API_URL || "").replace(/\\/+$/, "") + "/api/v1";'

count = 0
for filepath in glob.glob(os.path.join(src_dir, '**', '*.jsx'), recursive=True):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    
    for t in [target1, target2, target3]:
        if t in content:
            content = content.replace(t, replacement)
        elif t.replace('\n', '\r\n') in content:
            content = content.replace(t.replace('\n', '\r\n'), replacement)

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        count += 1
        print(f"Updated {filepath}")

print(f"Done. Updated {count} files.")
