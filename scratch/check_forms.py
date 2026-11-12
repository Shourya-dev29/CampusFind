import os
import re

for root, dirs, files in os.walk('templates'):
    for file in sorted(files):
        if file.endswith('.html'):
            p = os.path.join(root, file)
            with open(p, 'r', encoding='utf-8') as f:
                content = f.read()
                matches = re.findall(r'<form\b([^>]*)>(.*?)</form>', content, re.DOTALL | re.IGNORECASE)
                for idx, (form_tag, form_body) in enumerate(matches):
                    is_post = 'post' in form_tag.lower()
                    if is_post:
                        has_csrf = 'csrf_token' in form_body
                        print(f"{file:20} form #{idx+1} [POST]: has_csrf={has_csrf}")

