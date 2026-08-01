"""Generate the author-card HTML snippet with embedded CaptainRita photo."""
from PIL import Image
import base64, io, sys

img = Image.open('blogger-posts/CaptainRita/assets/CaptainRita.png').convert('RGB')
img = img.resize((96, 96), Image.LANCZOS)
buf = io.BytesIO()
img.save(buf, format='JPEG', quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()
data_uri = f'data:image/jpeg;base64,{b64}'

author_card = (
    '<div style="display:flex;align-items:center;gap:16px;margin-top:32px;'
    'padding:18px 20px;border-radius:18px;background:rgba(186,122,58,0.08);'
    'border:1px solid rgba(186,122,58,0.2);">'
    f'<img src="{data_uri}" alt="Captain Rita" style="width:72px;height:72px;'
    'border-radius:50%;object-fit:cover;object-position:center top;'
    'border:3px solid #ba7a3a;flex-shrink:0;">'
    '<div><strong style="display:block;font-size:16px;color:#2a241f;">Captain Rita</strong>'
    '<span style="font-size:13px;color:#8a6a4a;">Daily Quotations &middot; July 31, 2026</span>'
    '</div></div>'
)

print(author_card)
