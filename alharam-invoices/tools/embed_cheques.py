"""Turn the standalone cheque system page (src/cheques.html) into an embeddable module.

The cheque app runs inside a Shadow DOM in the invoicing page, so its styles and
element ids stay isolated, and it uses the page's own claude runtime (database,
downloads, assets). Its hash navigation is kept virtual so it never changes the
invoicing page's address.

Returns (css, html, js) where js defines window.__chequeApp(shadowRoot).
"""
import re


def transform(page: str):
    css = "\n".join(re.findall(r"<style>([\s\S]*?)</style>", page))
    # tokens: :root -> :host (theme toggles keep working through :host-context)
    css = css.replace(':root:not([data-theme="light"])', ":host")
    css = css.replace(':root[data-theme="dark"]', ':host-context([data-theme="dark"])')
    css = css.replace(":root", ":host")
    css = css.replace("html,body{margin:0}", ":host{display:block}")
    css = re.sub(r"(^|[}\s,])body(\s*\{)", r"\1.chq-body\2", css)

    body = page[page.index("<body"):]
    body = body[body.index(">") + 1:]
    body = body[: body.rindex("</body>")]
    body = re.sub(r"<script[\s\S]*?</script>", "", body).strip()
    html = f'<div class="chq-body">{body}</div>'

    js = "\n".join(re.findall(r"<script>([\s\S]*?)</script>", page))
    reps = [
        ("document.getElementById(", "__R.getElementById("),
        ("document.querySelectorAll(", "__R.querySelectorAll("),
        ("document.querySelector(", "__R.querySelector("),
        ("document.body.addEventListener(", "__R.addEventListener("),
        ('window.addEventListener("hashchange",', '__NAV.addEventListener("hashchange",'),
        ("location.hash", "__LOC.hash"),
    ]
    for a, b in reps:
        js = js.replace(a, b)
    wrapper = (
        "window.__chequeApp=function(__R){\n"
        "const __NAV=new EventTarget();\n"
        "const __LOC={_h:'',get hash(){return this._h;},set hash(v){v=String(v||'');this._h=v?(v[0]==='#'?v:'#'+v):'';__NAV.dispatchEvent(new Event('hashchange'));}};\n"
        "__R.addEventListener('click',function(e){var a=e.target&&e.target.closest?e.target.closest('a[href^=\"#\"]'):null;if(a){e.preventDefault();__LOC.hash=a.getAttribute('href');}});\n"
        + js +
        "\n};"
    )
    return css, html, wrapper
