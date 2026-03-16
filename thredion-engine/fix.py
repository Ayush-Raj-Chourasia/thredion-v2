import re
with open('tests/test_schema_validation.py', 'r', encoding='utf-8') as f:
    c = f.read()

prefix = '''        from db.models import User
        if not db.query(User).first():
            db.add(User(id="00000000-0000-0000-0000-000000000000", phone_number="1234567890"))
            db.commit()
'''
c = re.sub(r'(def test_.*?\((?:self, )?db\):)', lambda m: m.group(1) + '\n' + prefix, c)

with open('tests/test_schema_validation.py', 'w', encoding='utf-8') as f:
    f.write(c)
