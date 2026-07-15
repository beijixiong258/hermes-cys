---
name: powerpoint
description: "Use this skill any time a .pptx file is involved in any way — as input, output, or both. This includes: creating slide decks, pitch decks, or presentations; reading, parsing, or extracting text from any .pptx file (even if the extracted content will be used elsewhere, like in an email or summary); editing, modifying, or updating existing presentations; combining or splitting slide files; working with templates, layouts, speaker notes, or comments. Trigger whenever the user mentions \"deck,\" \"slides,\" \"presentation,\" or references a .pptx filename, regardless of what they plan to do with the content afterward. If a .pptx file needs to be opened, created, or touched, use this skill."
license: Proprietary. LICENSE.txt has complete terms
---

# Powerpoint Skill

## Quick Reference

| Task | Guide |
|------|-------|
| Read/analyze content | `python -m markitdown presentation.pptx` |
| Edit or create from template | Read [editing.md](editing.md) |
| Create from scratch | Read [pptxgenjs.md](pptxgenjs.md) |

---

## Reading Content

```bash
# Text extraction
python -m markitdown presentation.pptx

# Visual overview
python scripts/thumbnail.py presentation.pptx

# Raw XML
python scripts/office/unpack.py presentation.pptx unpacked/
```

---

## Editing Workflow

**Read [editing.md](editing.md) for full details.**

1. Analyze template with `thumbnail.py`
2. Unpack → manipulate slides → edit content → clean → pack

---

## Creating from Scratch

**Read [pptxgenjs.md](pptxgenjs.md) for full details.**

Use when no template or reference presentation is available.

---

## Design Ideas

**Don't create boring slides.** Plain bullets on a white background won't impress anyone. Consider ideas from this list for each slide.

### Before Starting

- **Pick a bold, content-informed color palette**: The palette should feel designed for THIS topic. If swapping your colors into a completely different presentation would still "work," you haven't made specific enough choices.
- **Dominance over equality**: One color should dominate (60-70% visual weight), with 1-2 supporting tones and one sharp accent. Never give all colors equal weight.
- **Dark/light contrast**: Dark backgrounds for title + conclusion slides, light for content ("sandwich" structure). Or commit to dark throughout for a premium feel.
- **Commit to a visual motif**: Pick ONE distinctive element and repeat it — rounded image frames, icons in colored circles, thick single-side borders. Carry it across every slide.

### Color Palettes

Choose colors that match your topic — don't default to generic blue. Use these palettes as inspiration:

| Theme | Primary | Secondary | Accent |
|-------|---------|-----------|--------|
| **Midnight Executive** | `1E2761` (navy) | `CADCFC` (ice blue) | `FFFFFF` (white) |
| **Forest & Moss** | `2C5F2D` (forest) | `97BC62` (moss) | `F5F5F5` (cream) |
| **Coral Energy** | `F96167` (coral) | `F9E795` (gold) | `2F3C7E` (navy) |
| **Warm Terracotta** | `B85042` (terracotta) | `E7E8D1` (sand) | `A7BEAE` (sage) |
| **Ocean Gradient** | `065A82` (deep blue) | `1C7293` (teal) | `21295C` (midnight) |
| **Charcoal Minimal** | `36454F` (charcoal) | `F2F2F2` (off-white) | `212121` (black) |
| **Teal Trust** | `028090` (teal) | `00A896` (seafoam) | `02C39A` (mint) |
| **Berry & Cream** | `6D2E46` (berry) | `A26769` (dusty rose) | `ECE2D0` (cream) |
| **Sage Calm** | `84B59F` (sage) | `69A297` (eucalyptus) | `50808E` (slate) |
| **Cherry Bold** | `990011` (cherry) | `FCF6F5` (off-white) | `2F3C7E` (navy) |

### For Each Slide

**Every slide needs a visual element** — image, chart, icon, or shape. Text-only slides are forgettable.

**Layout options:**
- Two-column (text left, illustration on right)
- Icon + text rows (icon in colored circle, bold header, description below)
- 2x2 or 2x3 grid (image on one side, grid of content blocks on other)
- Half-bleed image (full left or right side) with content overlay

**Data display:**
- Large stat callouts (big numbers 60-72pt with small labels below)
- Comparison columns (before/after, pros/cons, side-by-side options)
- Timeline or process flow (numbered steps, arrows)

**Visual polish:**
- Icons in small colored circles next to section headers
- Italic accent text for key stats or taglines

### Typography

**Choose an interesting font pairing** — don't default to Arial. Pick a header font with personality and pair it with a clean body font.

| Header Font | Body Font |
|-------------|-----------|
| Georgia | Calibri |
| Arial Black | Arial |
| Calibri | Calibri Light |
| Cambria | Calibri |
| Trebuchet MS | Calibri |
| Impact | Arial |
| Palatino | Garamond |
| Consolas | Calibri |

| Element | Size |
|---------|------|
| Slide title | 36-44pt bold |
| Section header | 20-24pt bold |
| Body text | 14-16pt |
| Captions | 10-12pt muted |

### Spacing

- 0.5" minimum margins
- 0.3-0.5" between content blocks
- Leave breathing room—don't fill every inch

### Avoid (Common Mistakes)

- **Don't repeat the same layout** — vary columns, cards, and callouts across slides
- **Don't center body text** — left-align paragraphs and lists; center only titles
- **Don't skimp on size contrast** — titles need 36pt+ to stand out from 14-16pt body
- **Don't default to blue** — pick colors that reflect the specific topic
- **Don't mix spacing randomly** — choose 0.3" or 0.5" gaps and use consistently
- **Don't style one slide and leave the rest plain** — commit fully or keep it simple throughout
- **Don't create text-only slides** — add images, icons, charts, or visual elements; avoid plain title + bullets
- **Don't forget text box padding** — when aligning lines or shapes with text edges, set `margin: 0` on the text box or offset the shape to account for padding
- **Don't use low-contrast elements** — icons AND text need strong contrast against the background; avoid light text on light backgrounds or dark text on dark backgrounds
- **NEVER use accent lines under titles** — these are a hallmark of AI-generated slides; use whitespace or background color instead

---

## QA (Required)

**Assume there are problems. Your job is to find them.**

Your first render is almost never correct. Approach QA as a bug hunt, not a confirmation step. If you found zero issues on first inspection, you weren't looking hard enough.

### Content QA

```bash
python -m markitdown output.pptx
```

Check for missing content, typos, wrong order.

**When using templates, check for leftover placeholder text:**

```bash
python -m markitdown output.pptx | grep -iE "xxxx|lorem|ipsum|this.*(page|slide).*layout"
```

If grep returns results, fix them before declaring success.

### Visual QA

**⚠️ USE SUBAGENTS** — even for 2-3 slides. You've been staring at the code and will see what you expect, not what's there. Subagents have fresh eyes.

Convert slides to images (see [Converting to Images](#converting-to-images)), then use this prompt:

```
Visually inspect these slides. Assume there are issues — find them.

Look for:
- Overlapping elements (text through shapes, lines through words, stacked elements)
- Text overflow or cut off at edges/box boundaries
- Decorative lines positioned for single-line text but title wrapped to two lines
- Source citations or footers colliding with content above
- Elements too close (< 0.3" gaps) or cards/sections nearly touching
- Uneven gaps (large empty area in one place, cramped in another)
- Insufficient margin from slide edges (< 0.5")
- Columns or similar elements not aligned consistently
- Low-contrast text (e.g., light gray text on cream-colored background)
- Low-contrast icons (e.g., dark icons on dark backgrounds without a contrasting circle)
- Text boxes too narrow causing excessive wrapping
- Leftover placeholder content

For each slide, list issues or areas of concern, even if minor.

Read and analyze these images:
1. /path/to/slide-01.jpg (Expected: [brief description])
2. /path/to/slide-02.jpg (Expected: [brief description])

Report ALL issues found, including minor ones.
```

### Verification Loop

1. Generate slides → Convert to images → Inspect
2. **List issues found** (if none found, look again more critically)
3. Fix issues
4. **Re-verify affected slides** — one fix often creates another problem
5. Repeat until a full pass reveals no new issues

**Do not declare success until you've completed at least one fix-and-verify cycle.**

### Visual QA Without Vision Support (XML Structural Analysis)

When the provider doesn't support vision/image analysis (e.g., DeepSeek text-only models) and subagent-based visual QA fails, fall back to XML-level structural analysis. This catches text overflow, truncation, and layout density problems that are invisible from plain text extraction alone.

**Extract text with stdlib xml.etree.ElementTree** (zero pip installs, works in WSL sandbox):

```python
import zipfile, os, xml.etree.ElementTree as ET

base = '/tmp/pptx_qa'
with zipfile.ZipFile('input.pptx', 'r') as z:
    z.extractall(base)

ns = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
}

# Parse slide list
pres = ET.parse(f'{base}/ppt/presentation.xml')
sld_lst = pres.getroot().find('.//p:sldIdLst', ns)
for i, sld in enumerate(sld_lst):
    rid = sld.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
    # ... resolve rid → slide file via _rels/presentation.xml.rels ...
    slide = ET.parse(f'{base}/ppt/slides/slide{i+1}.xml')
    
    for sp in slide.getroot().findall('.//p:sp', ns):
        # Get position and size
        xfrm = sp.find('.//a:xfrm', ns)
        off = xfrm.find('a:off', ns)
        ext = xfrm.find('a:ext', ns)
        cx, cy = int(ext.get('cx',0)), int(ext.get('cy',0))
        
        # Get text
        texts = [t.text for t in sp.findall('.//a:t', ns) if t.text and t.text.strip()]
        total_chars = sum(len(t) for t in texts)
        
        # Overflow risk check: rough estimate
        EMU_PER_INCH = 914400
        chars_per_line = (cx / EMU_PER_INCH) * 8  # ~8 chars/inch at 14pt
        lines_needed = total_chars / max(chars_per_line, 1)
        lines_available = (cy / EMU_PER_INCH) / 0.26  # ~0.26" per line at 14pt
        if lines_needed > lines_available * 1.3:
            print(f"  ⚠ OVERFLOW: {total_chars} chars in {cx/EMU_PER_INCH:.1f}\"x{cy/EMU_PER_INCH:.1f}\" box")
```

**Common overflow pattern**: Text boxes wider than 7" but narrower than 0.7" tall with 200+ chars are nearly always overflowing — these are footer-style strips crammed with body text.

**What this CAN detect**:
- Text overflow risk (char count vs box dimensions)
- Hard truncation (text ending in `...` or `…`)
- Placeholder/lorem ipsum leftovers
- Shape count anomalies (too few/many shapes per slide)
- Slide count mismatches vs expected

**What this CANNOT detect** (needs real vision):
- Color contrast and readability
- Actual clipping/cut-off (vs theoretical overflow risk)
- Element overlap and alignment precision
- Font size variations within a shape

### Academic Presentation Review

When reviewing slides for a paper presentation (thesis defense, conference talk, seminar), cross-reference the PPTX against three sources:

1. **The paper PDF** — extract via `pymupdf` (fitz) for the exact terminology, values, and examples
2. **The presentation script/speaker notes** — what the speaker actually plans to say
3. **The content outline** — what each slide is supposed to cover

**Methodology**:

1. Extract PPTX text (via markitdown or XML)
2. Extract paper PDF for the relevant sections (`pip install pymupdf --break-system-packages`)
3. Read script and outline files
4. Compare slide-by-slide:
   - **Terminology**: Do token names, variable names, and abbreviations match the paper exactly?
   - **Values/numbers**: Do counts (e.g., "4k–20k"), percentages (e.g., ">90%"), and scoring scales match?
   - **Examples**: Do the examples used in PPT match those the script references?
   - **Consistency**: If the script emphasizes a specific detail (e.g., "Partially Supported" as a key point), does the PPT highlight it?
5. Flag any PPT→script contradictions — the speaker will look at the slide while talking

**Common academic PPT bugs**:
- Truncated paper terminology ("Partially" instead of "Partially Supported")
- Example mismatch between paper's Figure X and the slide
- Using a different example city/name than what the paper's figure shows
- Script says one thing but slide shows another (e.g., script explains "Partially Supported" but slide shows "Supported")
- Missing paper section/page citations on slides

---

## Converting to Images

Convert presentations to individual slide images for visual inspection:

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
pdftoppm -jpeg -r 150 output.pdf slide
```

This creates `slide-01.jpg`, `slide-02.jpg`, etc.

To re-render specific slides after fixes:

```bash
pdftoppm -jpeg -r 150 -f N -l N output.pdf slide-fixed
```

---

## Dependencies

- `pip install "markitdown[pptx]"` - text extraction
- `pip install Pillow` - thumbnail grids
- `npm install -g pptxgenjs (see WSL note below if running from WSL)` - creating from scratch
- LibreOffice (`soffice`) - PDF conversion (auto-configured for sandboxed environments via `scripts/office/soffice.py`)
- Poppler (`pdftoppm`) - PDF to images

---

## Raw XML Manipulation (lxml + zipfile) — Fallback for Editing

When `python-pptx` is unavailable (missing Pillow/XlsxWriter deps, slow pip in WSL) or the skill's `unpack.py` script isn't found, use **lxml + zipfile** for direct PPTX XML editing. This approach works anywhere `lxml` is installed and avoids all dependency issues.

### Extraction & Repack

```python
import zipfile, os, shutil
from lxml import etree

# Extract PPTX (it's just a ZIP)
base = '/tmp/pptx_work'
with zipfile.ZipFile('input.pptx', 'r') as z:
    z.extractall(base)

# ... edit XML files (see below) ...

# Repack
with zipfile.ZipFile('output.pptx', 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(base):
        for fname in files:
            full = os.path.join(root, fname)
            z.write(full, os.path.relpath(full, base))
```

### Critical Namespace Pitfall

**`txBody` is in the `p:` namespace, NOT `a:`.** This is the most common silent failure — you'll think your edits worked but nothing changed.

```python
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
XML_NS = 'http://www.w3.org/XML/1998/namespace'

# ✅ CORRECT
txBody = shape.find(f'{{{P}}}txBody')

# ❌ WRONG — silently returns None
txBody = shape.find(f'{{{A}}}txBody')
```

### Removing Slides (keep only specific slides)

Three files must be cleaned in sync: `ppt/presentation.xml`, `[Content_Types].xml`, `ppt/_rels/presentation.xml.rels`. Also delete the slide XML files from `ppt/slides/` and `ppt/slides/_rels/`.

Find the mapping of slide numbers → rIds by parsing `<p:sldIdLst>` in `ppt/presentation.xml`:

```python
tree = etree.parse(f'{base}/ppt/presentation.xml')
lst = tree.find(f'.//{{{P}}}sldIdLst')
keep_rids = {'rId8', 'rId9', 'rId10'}  # e.g., keep slides 5-7
for child in list(lst):
    if child.get(f'{{{R_NS}}}id') not in keep_rids:
        lst.remove(child)
```

### Editing Text in Shapes

To replace text in a shape identified by its `<p:cNvPr name="...">`:

```python
def edit_shape_text(tree, shape_name, new_paragraphs):
    """Replace text in shape. new_paragraphs is list of strings (one per <a:p>)."""
    for sp in tree.findall(f'.//{{{P}}}sp'):
        nv = sp.find(f'{{{P}}}nvSpPr')
        if nv is None: continue
        cn = nv.find(f'{{{P}}}cNvPr')
        if cn is None or cn.get('name') != shape_name: continue
        
        txBody = sp.find(f'{{{P}}}txBody')  # NOTE: p: namespace, not a:
        if txBody is None: continue
        
        existing_ps = txBody.findall(f'{{{A}}}p')
        for i, para_text in enumerate(new_paragraphs):
            if i < len(existing_ps):
                ap = existing_ps[i]
            else:
                ap = existing_ps[-1].__copy__()  # clone last paragraph
                for r in ap.findall(f'{{{A}}}r'):
                    for t in r.findall(f'{{{A}}}t'):
                        t.text = ''
                txBody.append(ap)
            
            runs = ap.findall(f'{{{A}}}r')
            if runs:
                t_elems = runs[0].findall(f'{{{A}}}t')
                if t_elems:
                    t_elems[0].text = para_text
                    t_elems[0].set(f'{{{XML_NS}}}space', 'preserve')
                    for extra_t in t_elems[1:]:
                        extra_t.text = ''
                for extra_r in runs[1:]:
                    for t in extra_r.findall(f'{{{A}}}t'):
                        t.text = ''
        
        # Remove excess paragraphs
        for extra_p in existing_ps[len(new_paragraphs):]:
            txBody.remove(extra_p)
        return True
    return False
```

**Important**: This preserves existing `<a:rPr>` formatting (font, size, color) from the first run. If new paragraphs exceed the original count, the last paragraph's structure is cloned.

### Reading Text from PPTX without markitdown

When `python -m markitdown` fails:

```python
for sp in tree.findall(f'.//{{{P}}}sp'):
    nv = sp.find(f'{{{P}}}nvSpPr')
    if nv is not None:
        cn = nv.find(f'{{{P}}}cNvPr')
        if cn is not None:
            name = cn.get('name')
            ts = sp.findall(f'.//{{{A}}}t')
            texts = [t.text for t in ts if t.text and t.text.strip()]
            if texts:
                print(f'  [{name}]')
                for t in texts:
                    print(f'    {t.strip()[:120]}')
```

### When to Use This Fallback

- `python-pptx` dependency chain fails to install (Pillow, XlsxWriter)
- Skill scripts (`unpack.py`, `add_slide.py`) are not accessible
- Need to surgically edit a few slides in an existing PPTX without full round-trip risk
- WSL environment where pip installs are slow or blocked

Prefer the standard `editing.md` workflow when tools are available. Use this as a reliable escape hatch.

---

## Raw XML Manipulation (lxml + zipfile) — Fallback for Editing

When `python-pptx` is unavailable (missing Pillow/XlsxWriter deps, slow pip in WSL) or the skill's `unpack.py` script isn't found, use **lxml + zipfile** for direct PPTX XML editing. This approach works anywhere `lxml` is installed and avoids all dependency issues.

### Extraction & Repack

```python
import zipfile, os, shutil
from lxml import etree

# Extract PPTX (it's just a ZIP)
base = '/tmp/pptx_work'
with zipfile.ZipFile('input.pptx', 'r') as z:
    z.extractall(base)

# ... edit XML files (see below) ...

# Repack
with zipfile.ZipFile('output.pptx', 'w', zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(base):
        for fname in files:
            full = os.path.join(root, fname)
            z.write(full, os.path.relpath(full, base))
```

### Critical Namespace Pitfall

**`txBody` is in the `p:` namespace, NOT `a:`.** This is the most common silent failure — you'll think your edits worked but nothing changed.

```python
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
XML_NS = 'http://www.w3.org/XML/1998/namespace'

# ✅ CORRECT
txBody = shape.find(f'{{{P}}}txBody')

# ❌ WRONG — silently returns None
txBody = shape.find(f'{{{A}}}txBody')
```

### Removing Slides (keep only specific slides)

Three files must be cleaned in sync: `ppt/presentation.xml`, `[Content_Types].xml`, `ppt/_rels/presentation.xml.rels`. Also delete the slide XML files from `ppt/slides/` and `ppt/slides/_rels/`.

Find the mapping of slide numbers → rIds by parsing `<p:sldIdLst>` in `ppt/presentation.xml`:

```python
tree = etree.parse(f'{base}/ppt/presentation.xml')
lst = tree.find(f'.//{{{P}}}sldIdLst')
keep_rids = {'rId8', 'rId9', 'rId10'}  # e.g., keep slides 5-7
for child in list(lst):
    if child.get(f'{{{R_NS}}}id') not in keep_rids:
        lst.remove(child)
```

### Editing Text in Shapes

To replace text in a shape identified by its `<p:cNvPr name="...">`:

```python
def edit_shape_text(tree, shape_name, new_paragraphs):
    """Replace text in shape. new_paragraphs is list of strings (one per <a:p>)."""
    for sp in tree.findall(f'.//{{{P}}}sp'):
        nv = sp.find(f'{{{P}}}nvSpPr')
        if nv is None: continue
        cn = nv.find(f'{{{P}}}cNvPr')
        if cn is None or cn.get('name') != shape_name: continue
        
        txBody = sp.find(f'{{{P}}}txBody')  # NOTE: p: namespace, not a:
        if txBody is None: continue
        
        existing_ps = txBody.findall(f'{{{A}}}p')
        for i, para_text in enumerate(new_paragraphs):
            if i < len(existing_ps):
                ap = existing_ps[i]
            else:
                ap = existing_ps[-1].__copy__()  # clone last paragraph
                for r in ap.findall(f'{{{A}}}r'):
                    for t in r.findall(f'{{{A}}}t'):
                        t.text = ''
                txBody.append(ap)
            
            runs = ap.findall(f'{{{A}}}r')
            if runs:
                t_elems = runs[0].findall(f'{{{A}}}t')
                if t_elems:
                    t_elems[0].text = para_text
                    t_elems[0].set(f'{{{XML_NS}}}space', 'preserve')
                    for extra_t in t_elems[1:]:
                        extra_t.text = ''
                for extra_r in runs[1:]:
                    for t in extra_r.findall(f'{{{A}}}t'):
                        t.text = ''
        
        # Remove excess paragraphs
        for extra_p in existing_ps[len(new_paragraphs):]:
            txBody.remove(extra_p)
        return True
    return False
```

**Important**: This preserves existing `<a:rPr>` formatting (font, size, color) from the first run. If new paragraphs exceed the original count, the last paragraph's structure is cloned.

### Reading Text from PPTX without markitdown

When `python -m markitdown` fails:

```python
for sp in tree.findall(f'.//{{{P}}}sp'):
    nv = sp.find(f'{{{P}}}nvSpPr')
    if nv is not None:
        cn = nv.find(f'{{{P}}}cNvPr')
        if cn is not None:
            name = cn.get('name')
            ts = sp.findall(f'.//{{{A}}}t')
            texts = [t.text for t in ts if t.text and t.text.strip()]
            if texts:
                print(f'  [{name}]')
                for t in texts:
                    print(f'    {t.strip()[:120]}')
```

### When to Use This Fallback

- `python-pptx` dependency chain fails to install (Pillow, XlsxWriter)
- Skill scripts (`unpack.py`, `add_slide.py`) are not accessible
- Need to surgically edit a few slides in an existing PPTX without full round-trip risk
- WSL environment where pip installs are slow or blocked

Prefer the standard `editing.md` workflow when tools are available. Use this as a reliable escape hatch.

---

## Running pptxgenjs from WSL

When the agent runs inside WSL but node.exe is on the Windows host, there are three path pitfalls that each cause silent failures. Follow the recipe below exactly.

### 1. node.exe must be invoked by full Windows-accessible path

```bash
# ❌ WRONG — bash can't find node
node make_ppt.js

# ✅ CORRECT
"/mnt/c/Program Files/nodejs/node.exe" make_ppt.js
```

### 2. npm packages must be installed in a Windows-accessible directory

Global npm installs from WSL may resolve to the Windows npm prefix, but Windows node.exe cannot resolve `require()` from WSL-style paths. Even `NODE_PATH` set to `C:\Users\<user>\AppData\Roaming\npm\node_modules` does not bridge this gap.

**Solution: install pptxgenjs locally in a `/mnt/c/...` directory.**

```bash
cd /mnt/c/temp
"/mnt/c/Program Files/nodejs/npm" install pptxgenjs
```

Then place the `.js` script in the same directory and run from there:

```bash
cd /mnt/c/temp
"/mnt/c/Program Files/nodejs/node.exe" make_ppt.js
```

### 3. Output path in the JS script must use Windows format

Node runs in Windows context, so paths like `/mnt/c/Users/user/Desktop/file.pptx` get prefixed with `C:` → `C:\mnt\c\Users\...` which doesn't exist.

```javascript
// ❌ WRONG — becomes C:\mnt\c\Users\... (ENOENT)
pres.writeFile({ fileName: "/mnt/c/Users/user/Desktop/output.pptx" })

// ✅ CORRECT
pres.writeFile({ fileName: "C:\\Users\\user\\Desktop\\output.pptx" })
```

### Complete WSL invocation template

```bash
cd /mnt/c/temp
"/mnt/c/Program Files/nodejs/npm" install pptxgenjs   # first time only
# ... write make_ppt.js with Windows output paths ...
"/mnt/c/Program Files/nodejs/node.exe" make_ppt.js
```
