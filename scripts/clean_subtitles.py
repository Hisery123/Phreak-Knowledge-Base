"""Clean local YouTube WebVTT files; retain timestamps and source URLs."""
import argparse
import html
import json
import re
from pathlib import Path

TIME = re.compile(r'^(\d{2,}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s+-->\s+(\S+)')
TAG = re.compile(r'<[^>]*>')
NAME = re.compile(r'^(\d{8})_(.{11})\.[^.]+\.vtt$')

def seconds(t):
    parts = t.split(':')
    return sum(float(x) * 60 ** i for i, x in enumerate(reversed(parts)))

def clean(text):
    if not text.lstrip('\ufeff').startswith('WEBVTT'):
        raise ValueError('Not a WebVTT file')
    records, previous, prev_end = [], [], -100
    for block in re.split(r'\n[ \t]*\n', text.replace('\r\n', '\n').replace('\r', '\n')):
        lines = block.splitlines()
        for i, line in enumerate(lines):
            match = TIME.match(line.strip())
            if match:
                break
        else:
            continue
        start, end = match.groups()
        words = html.unescape(TAG.sub('', ' '.join(lines[i+1:]))).split()
        if not words:
            continue
        # Rolling captions repeat the tail of the immediately preceding cue.
        # Never remove repeated phrases across a gap.
        overlap = 0
        if abs(seconds(start) - prev_end) <= 0.15 or seconds(start) < prev_end:
            for n in range(min(len(previous), len(words)), 0, -1):
                if previous[-n:] == words[:n]:
                    overlap = n
                    break
        fresh = words[overlap:]
        if fresh:
            records.append((start, ' '.join(fresh)))
        previous, prev_end = words, seconds(end)
    if not records:
        raise ValueError('No readable caption cues')
    return records

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    root = args.root.resolve()
    src, out, meta = (root / 'data' / x for x in ('subtitles', 'transcripts', 'metadata'))
    out.mkdir(parents=True, exist_ok=True)
    meta.mkdir(parents=True, exist_ok=True)
    files = sorted(src.glob('*.vtt'))
    if not files:
        raise SystemExit('No VTT files found in ' + str(src))
    results = []
    for path in files:
        try:
            m = NAME.fullmatch(path.name)
            if not m:
                raise ValueError('Unexpected filename')
            date, vid = m.groups()
            stem = f'{date}_{vid}'
            records = clean(path.read_text(encoding='utf-8-sig'))
            info_path = src / (stem + '.info.json')
            info = json.loads(info_path.read_text(encoding='utf-8-sig')) if info_path.exists() else {}
            data = {'id': vid, 'upload_date': date, 'url': f'https://www.youtube.com/watch?v={vid}', 'title': info.get('title'), 'duration': info.get('duration'), 'source_language': path.name.split('.')[-2], 'cue_count': len(records), 'word_count': sum(len(t.split()) for _, t in records), 'source_file': path.name}
            # Group into short blocks while retaining the first cue timestamp.
            blocks = []
            for stamp, text in records:
                if not blocks or seconds(stamp) - seconds(blocks[-1][0]) >= 20:
                    blocks.append((stamp, [text]))
                else:
                    blocks[-1][1].append(text)
            body = '\n\n'.join(f'[{stamp}] ' + ' '.join(parts) for stamp, parts in blocks)
            (out / (stem + '.md')).write_text(f"# {data['title'] or vid}\n\nSource: {data['url']}\nDate: {date}\nLanguage: {data['source_language']} (automatic captions; not verified)\n\n" + body + '\n', encoding='utf-8')
            (meta / (stem + '.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            results.append(data)
            print(f"OK {path.name}: {data['word_count']} words")
        except Exception as exc:
            results.append({'source_file': path.name, 'error': str(exc)})
            print(f'ERROR {path.name}: {exc}')
    logs = root / 'logs'
    logs.mkdir(exist_ok=True)
    (logs / 'clean_report.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    failed = sum('error' in row for row in results)
    print(f'Finished: {len(results)-failed}/{len(results)} successful; {failed} failed')
    return int(bool(failed))

if __name__ == '__main__':
    raise SystemExit(main())
