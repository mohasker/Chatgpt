"""Build the two deliverables from src/app.html, inlining the brand images
and the embedded cheque system (src/cheques.html).

  dist/artifact.html  page body published as the Claude Artifact (cloud database)
  dist/index.html     standalone copy that runs from any web host or a local
                      file (data kept in that browser; direct printing works)

Usage:  python3 build.py
"""
import json
from pathlib import Path

root = Path(__file__).parent
html = (root / "src" / "app.html").read_text(encoding="utf-8")
for key in ("logo", "strip", "sign", "stamp"):
    data = (root / "assets" / f"{key}.b64").read_text().strip()
    html = html.replace("{{%s}}" % key.upper(), data)

cheques = root / "src" / "cheques.html"
if cheques.exists():
    # JSON string literal; "</" escaped so the embedded page cannot close our <script>
    lit = json.dumps(cheques.read_text(encoding="utf-8"), ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("{{CHEQUE_HTML}}", lit)

dist = root / "dist"
dist.mkdir(exist_ok=True)
(dist / "artifact.html").write_text(html, encoding="utf-8")
standalone = (
    '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
    "<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}"
    "body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>"
    "</head><body>" + html + "</body></html>"
)
(dist / "index.html").write_text(standalone, encoding="utf-8")
for f in ("artifact.html", "index.html"):
    print(f"wrote dist/{f} ({(dist / f).stat().st_size // 1024} KB)")
