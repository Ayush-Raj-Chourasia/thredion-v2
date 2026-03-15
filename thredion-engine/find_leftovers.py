import os, re
for root, _, files in os.walk('.'):
    if '.venv' in root or '__pycache__' in root: continue
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as file:
                try:
                    content = file.read()
                    matches = re.finditer(r'user_phone|\.phone\b|topic_graph|memory\.url|memory\.content|memory\.thumbnail_url|importance_reasons|json\.loads\(memory\.tags\)|json\.loads\(memory\.importance_reasons\)', content)
                    for m in matches:
                        line_start = content.rfind('\n', 0, m.start()) + 1
                        line_end = content.find('\n', m.start())
                        print(f"{path}: {content[line_start:line_end]}")
                except Exception:
                    pass
