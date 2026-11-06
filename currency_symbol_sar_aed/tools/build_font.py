"""Build static/fonts/sar_aed_signs.ttf from two openly licensed fonts:

* U+20C1 SAUDI RIYAL SIGN from the Saudi Riyal Font (OFL-1.1),
  npm @emran-alhaddad/saudi-riyal-font 1.1.0, fonts/regular/saudi_riyal.ttf
* U+20C3 UAE DIRHAM SIGN from the dirham package (MIT),
  npm dirham 1.5.3, dist/fonts/dirham.ttf

Only those two code points are kept: the riyal font also maps A-D and U+20C0,
which would replace those letters wherever the font is used. Both glyphs are
scaled to cap height and set on the baseline, so they sit like a capital
letter next to the amount.

    python tools/build_font.py saudi_riyal.ttf dirham.ttf static/fonts/sar_aed_signs.ttf
"""
import sys

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

UPM = 1000
HEIGHT = 700  # about the cap height of Odoo's UI and report fonts
SIDE = 60     # side bearing on each side
FAMILY = 'SAR AED Signs'


def take(path, codepoint):
    """The glyph mapped to `codepoint` in `path`, scaled to HEIGHT and placed
    on the baseline: (glyph, advance width)."""
    font = TTFont(path)
    glyphs = font.getGlyphSet()
    source = glyphs[font.getBestCmap()[codepoint]]
    bounds = BoundsPen(glyphs)
    source.draw(bounds)
    xmin, ymin, xmax, ymax = bounds.bounds
    scale = HEIGHT / (ymax - ymin)
    pen = TTGlyphPen(glyphs)
    source.draw(TransformPen(pen, (scale, 0, 0, scale, SIDE - xmin * scale, -ymin * scale)))
    return pen.glyph(), round((xmax - xmin) * scale) + 2 * SIDE


def main(riyal_path, dirham_path, out_path):
    riyal, riyal_width = take(riyal_path, 0x20C1)
    dirham, dirham_width = take(dirham_path, 0x20C3)
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(['.notdef', 'uni20C1', 'uni20C3'])
    fb.setupCharacterMap({0x20C1: 'uni20C1', 0x20C3: 'uni20C3'})
    fb.setupGlyf({'.notdef': TTGlyphPen(None).glyph(), 'uni20C1': riyal, 'uni20C3': dirham})
    fb.setupHorizontalMetrics({
        '.notdef': (500, 0),
        'uni20C1': (riyal_width, SIDE),
        'uni20C3': (dirham_width, SIDE),
    })
    # A one-em line box: never taller than the text font it stands in for.
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({
        'familyName': FAMILY,
        'styleName': 'Regular',
        'copyright': 'Saudi riyal sign: derived from Saudi Riyal Font (c) Emran Alhaddad, '
                     'SIL Open Font License 1.1. UAE dirham sign: (c) 2025 '
                     'dirham-symbol contributors, MIT License. SAR AED Signs is a '
                     'modified version of the Saudi Riyal Font.',
        'licenseDescription': 'This Font Software is licensed under the SIL Open Font '
                              'License, Version 1.1.',
        'licenseInfoURL': 'https://openfontlicense.org',
    })
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0,
                usWinAscent=800, usWinDescent=200, sCapHeight=HEIGHT, sxHeight=500,
                fsType=0, achVendID='NONE')
    fb.setupPost()
    fb.save(out_path)


if __name__ == '__main__':
    main(*sys.argv[1:4])
