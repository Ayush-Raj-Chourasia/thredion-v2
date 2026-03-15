import os

with open('api/routes.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('"platform": memory.platform,', '"platform": getattr(memory, ''platform'', None),')

with open('api/routes.py', 'w', encoding='utf-8') as f:
    f.write(c)

with open('services/resurfacing.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('from db.models import Memory, ResurfacedMemory', 'from db.models import Memory, ResurfacedMemory, User')

with open('services/resurfacing.py', 'w', encoding='utf-8') as f:
    f.write(c)
