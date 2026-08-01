from pathlib import Path

files = [
    Path('booklets/dr-newton-kondaveeti-buddhi-yogam-tadipatri-shuddhi-siddhi-buddhi-pyramid-meditation.kindle.md'),
    Path('booklets/dr-newton-kondaveeti-buddhi-yogam-tadipatri-buddhi-takes-the-final-decision.kindle.md'),
]
output = Path('booklets/dr-newton-kondaveeti-buddhi-yogam-tadipatri-pa-07-08-consolidated.kindle.md')


def reflow_md(text: str) -> str:
    lines = text.splitlines()
    out = []
    para = []

    def flush_para():
        if para:
            line = ' '.join(para)
            line = ' '.join(line.split())
            out.append(line)
            out.append('')
            para.clear()

    for line in lines:
        stripped = line.rstrip()
        if stripped == '':
            flush_para()
        elif stripped.lstrip().startswith('#'):
            flush_para()
            out.append(stripped)
            out.append('')
        else:
            para.append(stripped.strip())
    flush_para()

    while out and out[-1] == '':
        out.pop()

    return '\n'.join(out) + '\n'

with output.open('w', encoding='utf-8') as f:
    f.write('# Dr. Newton Kondaveti Buddhi Yogam Tadipatri — Consolidated Talk\n\n')
    f.write('## Reading order: first Shuddhi, Siddhi and Buddhi through Pyramid Meditation, then Buddhi Takes The Final Decision.\n\n')
    f.write('This consolidated file combines two Tadipatri talks into one document for smoother reading and better comprehension.\n\n')

    for path in files:
        text = path.read_text(encoding='utf-8')
        if 'shuddhi-siddhi-buddhi-pyramid' in path.name:
            f.write('## Part 1: శుద్ధి, సిద్ధి, బుద్ధి: పిరమిడ్ ధ్యానంలో\n\n')
        else:
            f.write('## Part 2: బుద్ధి తుది నిర్ణయం తీసుకోవడం\n\n')
        f.write(reflow_md(text))
        f.write('\n')

print(f'Wrote {output}')
