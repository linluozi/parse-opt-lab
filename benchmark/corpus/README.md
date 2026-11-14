# Corpus provenance

Source: `/var/lib/dpkg/status` on the Ubuntu 24.04 machine that ran the
benchmark (file mtime 2026-11-12).  Only lines starting with
`Package: `, `Version: ` or `Depends: ` were kept, in file order.

Extraction (reproducible, no filtering by value):

```bash
python3 - <<'PY'
import re
lines = open('/var/lib/dpkg/status', encoding='utf-8').read().splitlines()
keep = [l for l in lines if re.match(r'^(Package|Version|Depends): ', l)]
open('dpkg-status-lines.txt', 'w').write('\n'.join(keep[:8000]) + '\n')
PY
```

- lines: 3,143 (1,083 `Package`, 1,083 `Version`, 977 `Depends`)
- bytes: 143,457
- sha256: `7c3c718e7ac311f696d2826fe5045015d8239a9d656715976adfd20676a114fa`

This is real package metadata, not generated data.  It contains no secrets;
maintainer names/addresses are the public fields shipped in every Ubuntu
installation.  It is included only as a realistic parsing input.
