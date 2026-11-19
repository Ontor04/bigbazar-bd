"""Generates the simple demo product pictures (replace them from Admin → Products)."""
import os
OUT = os.path.join(os.path.dirname(__file__), "..", "static", "img", "demo")
OR, BR, CR, YE = "#FF7518", "#4B3A35", "#FFF1E3", "#FFC93C"

def svg(name, body, bg1="#FFF6EC", bg2="#FFE2C6"):
    s = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400" role="img" aria-label="{name}">
<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{bg1}"/><stop offset="1" stop-color="{bg2}"/></linearGradient>
<filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="9"/></filter></defs>
<rect width="400" height="400" fill="url(#bg)"/><circle cx="200" cy="210" r="150" fill="#fff" opacity=".55"/>
{body}
<ellipse cx="200" cy="352" rx="110" ry="9" fill="#4B3A35" opacity=".12"/></svg>'''
    open(os.path.join(OUT, name + ".svg"), "w", encoding="utf-8").write(s)

svg("earbuds", f'''<rect x="105" y="215" width="190" height="115" rx="42" fill="{BR}"/><rect x="105" y="215" width="190" height="52" rx="42" fill="#6A5750"/>
<circle cx="200" cy="270" r="9" fill="{YE}"/>
<circle cx="150" cy="150" r="36" fill="{OR}"/><rect x="172" y="146" width="17" height="76" rx="8.5" fill="{OR}"/><circle cx="146" cy="146" r="12" fill="#fff" opacity=".35"/>
<circle cx="250" cy="150" r="36" fill="{OR}"/><rect x="211" y="146" width="17" height="76" rx="8.5" fill="{OR}"/><circle cx="246" cy="146" r="12" fill="#fff" opacity=".35"/>''')
svg("powerbank", f'''<rect x="128" y="82" width="144" height="236" rx="26" fill="{BR}"/><rect x="128" y="82" width="144" height="236" rx="26" fill="none" stroke="#6A5750" stroke-width="4"/>
<rect x="170" y="70" width="60" height="18" rx="5" fill="#2B211E"/>
<g fill="{OR}"><rect x="152" y="120" width="96" height="14" rx="7"/><rect x="152" y="146" width="96" height="14" rx="7"/><rect x="152" y="172" width="96" height="14" rx="7"/></g><rect x="152" y="198" width="46" height="14" rx="7" fill="{YE}"/>
<path d="M200 318 C 200 370, 300 360, 320 330" fill="none" stroke="{OR}" stroke-width="10" stroke-linecap="round"/>''')
svg("smartwatch", f'''<rect x="165" y="50" width="70" height="300" rx="22" fill="{BR}"/>
<rect x="128" y="128" width="144" height="144" rx="38" fill="#2B211E"/><rect x="140" y="140" width="120" height="120" rx="28" fill="#17110F"/>
<circle cx="200" cy="200" r="46" fill="none" stroke="{OR}" stroke-width="6" opacity=".9"/><line x1="200" y1="200" x2="200" y2="166" stroke="#fff" stroke-width="6" stroke-linecap="round"/><line x1="200" y1="200" x2="224" y2="212" stroke="{YE}" stroke-width="6" stroke-linecap="round"/>
<rect x="270" y="170" width="9" height="30" rx="4" fill="#6A5750"/>''')
svg("ledstrip", f'''<defs><linearGradient id="rg" x1="0" x2="1"><stop offset="0" stop-color="{OR}"/><stop offset=".35" stop-color="{YE}"/><stop offset=".7" stop-color="#FF4D8D"/><stop offset="1" stop-color="#3DC1D3"/></linearGradient></defs>
<path d="M40 270 C 110 130, 170 370, 240 220 S 340 130, 372 170" fill="none" stroke="url(#rg)" stroke-width="30" stroke-linecap="round" filter="url(#glow)" opacity=".75"/>
<path d="M40 270 C 110 130, 170 370, 240 220 S 340 130, 372 170" fill="none" stroke="url(#rg)" stroke-width="12" stroke-linecap="round"/>
<path d="M40 270 C 110 130, 170 370, 240 220 S 340 130, 372 170" fill="none" stroke="#fff" stroke-width="3" stroke-dasharray="2 14" stroke-linecap="round"/>
<rect x="150" y="300" width="100" height="40" rx="12" fill="{BR}"/><g fill="{OR}"><circle cx="175" cy="320" r="7"/><circle cx="200" cy="320" r="7"/><circle cx="225" cy="320" r="7"/></g>''', "#F3EEFF", "#FFE9D6")
svg("tshirt", f'''<path d="M140 88 L96 118 L54 172 L98 204 L130 182 L130 322 L270 322 L270 182 L302 204 L346 172 L304 118 L260 88 C 246 118, 154 118, 140 88 Z" fill="{OR}"/>
<path d="M140 88 C 154 118, 246 118, 260 88" fill="none" stroke="{BR}" stroke-width="10" stroke-linecap="round"/>
<path d="M150 150 L250 150" stroke="#fff" stroke-width="3" opacity=".4"/><circle cx="200" cy="230" r="26" fill="#fff" opacity=".25"/>''')
svg("facewash", f'''<path d="M148 118 h104 l-12 192 a22 22 0 0 1-22 20 h-36 a22 22 0 0 1-22-20 z" fill="#6FBF73"/>
<rect x="164" y="72" width="72" height="50" rx="12" fill="{BR}"/><rect x="174" y="60" width="52" height="16" rx="6" fill="#6A5750"/>
<ellipse cx="200" cy="228" rx="38" ry="48" fill="{CR}"/><path d="M200 196 C 178 220, 190 252, 200 262 C 212 250, 222 220, 200 196 Z" fill="#6FBF73"/>''', "#F0FAEF", "#FFEBD6")
svg("analogwatch", f'''<rect x="168" y="40" width="64" height="320" rx="22" fill="{BR}"/><circle cx="200" cy="200" r="94" fill="{OR}"/><circle cx="200" cy="200" r="80" fill="{CR}"/>
<g stroke="{BR}" stroke-width="5" stroke-linecap="round"><line x1="200" y1="132" x2="200" y2="144"/><line x1="200" y1="256" x2="200" y2="268"/><line x1="132" y1="200" x2="144" y2="200"/><line x1="256" y1="200" x2="268" y2="200"/></g>
<line x1="200" y1="200" x2="200" y2="148" stroke="{BR}" stroke-width="7" stroke-linecap="round"/><line x1="200" y1="200" x2="236" y2="218" stroke="{OR}" stroke-width="6" stroke-linecap="round"/><circle cx="200" cy="200" r="8" fill="{BR}"/>''')
svg("yogamat", '''<rect x="112" y="205" width="226" height="118" rx="10" fill="#2EB6A8"/><rect x="112" y="205" width="226" height="22" fill="#fff" opacity=".18"/>
<circle cx="112" cy="264" r="58" fill="#1F8F84"/><circle cx="112" cy="264" r="42" fill="#2EB6A8"/><circle cx="112" cy="264" r="26" fill="#1F8F84"/><circle cx="112" cy="264" r="10" fill="#2EB6A8"/>''', "#E9FAF7", "#FFEBD6")
svg("bottle", f'''<rect x="148" y="108" width="104" height="226" rx="32" fill="#9AA7B2"/><rect x="148" y="108" width="40" height="226" rx="20" fill="#fff" opacity=".28"/>
<rect x="164" y="66" width="72" height="52" rx="14" fill="{OR}"/><rect x="148" y="196" width="104" height="30" fill="{OR}"/>''', "#EEF3F7", "#FFE9D6")
svg("neckfan", f'''<path d="M108 146 C 108 332, 292 332, 292 146" fill="none" stroke="{OR}" stroke-width="36" stroke-linecap="round"/>
<g><circle cx="108" cy="140" r="40" fill="{BR}"/><circle cx="292" cy="140" r="40" fill="{BR}"/>
<g stroke="#fff" stroke-width="7" stroke-linecap="round"><path d="M108 140 l0 -26 M108 140 l22 13 M108 140 l-22 13"/><path d="M292 140 l0 -26 M292 140 l22 13 M292 140 l-22 13"/></g></g>''', "#E8F6FB", "#FFEBD6")

open(os.path.join(OUT, "..", "placeholder.svg"), "w").write('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect width="400" height="400" fill="#FFF1E3"/><g fill="none" stroke="#FF7518" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" opacity=".7"><rect x="120" y="130" width="160" height="140" rx="18"/><circle cx="165" cy="180" r="14"/><path d="M280 240 l-52-52 -108 82"/></g></svg>''')
print("done")
