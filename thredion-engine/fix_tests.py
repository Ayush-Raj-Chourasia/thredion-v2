import os, re
# Let's fix test files
for root, _, files in os.walk('tests'):
    if '__pycache__' in root: continue
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            with open(path, 'r', encoding='utf-8') as file:
                try:
                    c = file.read()
                    c2 = re.sub(r'\buser_phone\b', 'user_id', c)
                    c2 = re.sub(r'user\.phone', 'user.id', c2)
                    if c != c2:
                        with open(path, 'w', encoding='utf-8') as fw:
                            fw.write(c2)
                        print(f"Fixed {path}")
                except Exception:
                    pass
