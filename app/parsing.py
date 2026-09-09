import re


def _parse_fqn(raw: str) -> str:
    """Clean a matched FQN."""
    return raw.strip('`').replace('`', '')


# Patterns that detect operations. Each pattern captures the FQN at the end.
# Order matters: more specific patterns first.
_OP_PATTERNS = [
    (re.compile(r'\bCALL\s+([\w.-]+(?:\.[\w.-]+){1,2})\s*\(', re.IGNORECASE), 'call', 'routine'),
    (re.compile(r'\bCREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.-]+(?:\.[\w.-]+){1,2})', re.IGNORECASE), 'create', 'table'),
    (re.compile(r'\bINSERT\s+INTO\s+([\w.-]+(?:\.[\w.-]+){1,2})', re.IGNORECASE), 'insert', 'table'),
    (re.compile(r'\bMERGE\s+INTO\s+([\w.-]+(?:\.[\w.-]+){1,2})', re.IGNORECASE), 'merge', 'table'),
    (re.compile(r'\b(?:DELETE\s+FROM|TRUNCATE\s+TABLE)\s+([\w.-]+(?:\.[\w.-]+){1,2})', re.IGNORECASE), 'delete', 'table'),
    (re.compile(r'\bFROM\s+([\w.-]+(?:\.[\w.-]+){1,2})', re.IGNORECASE), 'read', 'table'),
]


def parse_routine_body(body: str) -> dict:
    """Parse a routine body and extract dependencies/operations in order."""
    if not body:
        return {"operations": [], "has_dynamic_sql": False}

    has_dynamic_sql = bool(re.search(r'EXECUTE\s+IMMEDIATE', body, re.IGNORECASE))

    # Strip backticks for matching
    sb = body.replace('`', '')

    # Collect matches from the specific patterns first, tracking the span each
    # one consumes. The generic "read" (FROM) pattern is evaluated last and any
    # match whose span overlaps one already claimed is dropped - e.g. the FROM
    # in "DELETE FROM x" would otherwise also register as a spurious read of x.
    all_matches = []
    claimed_spans = []
    read_pattern_matches = []

    for pat, op_type, target_type in _OP_PATTERNS:
        for m in pat.finditer(sb):
            if op_type == 'read':
                read_pattern_matches.append(m)
                continue
            all_matches.append((m.start(), m.group(1), op_type, target_type))
            claimed_spans.append((m.start(), m.end()))

    for m in read_pattern_matches:
        start, end = m.start(), m.end()
        if any(start < c_end and end > c_start for c_start, c_end in claimed_spans):
            continue
        all_matches.append((m.start(), m.group(1), 'read', 'table'))

    # Sort by position in the body (preserves SQL order)
    all_matches.sort(key=lambda x: x[0])

    operations = []
    seq = 0
    seen = set()

    for pos, fqn_raw, op_type, target_type in all_matches:
        fqn = _parse_fqn(fqn_raw)
        dedup_key = (op_type, fqn)
        if dedup_key not in seen:
            seq += 1
            operations.append({
                "type": op_type,
                "target": fqn,
                "target_type": target_type,
                "sequence": seq,
            })
            seen.add(dedup_key)

    return {
        "operations": operations,
        "has_dynamic_sql": has_dynamic_sql,
    }
