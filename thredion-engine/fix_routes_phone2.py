import os

with open('api/routes.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('user_phone=user_phone', 'user_id=user_id')

with open('api/routes.py', 'w', encoding='utf-8') as f:
    f.write(c)
