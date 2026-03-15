import os

with open('api/routes.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('"platform": getattr(memory, platform, None),', '"platform": getattr(memory, \"platform\", None),')

with open('api/routes.py', 'w', encoding='utf-8') as f:
    f.write(c)

with open('services/resurfacing.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('from db.models import Memory, ResurfacedMemory, User, User', 'from db.models import Memory, ResurfacedMemory, User')

with open('services/resurfacing.py', 'w', encoding='utf-8') as f:
    f.write(c)
