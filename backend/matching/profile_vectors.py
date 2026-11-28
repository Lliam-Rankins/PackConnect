"""Keep per-phrase profile embeddings in step with profile text.

Each field is split into phrases (matching.chunking); every phrase is a chunk row.

Postgres is the retry queue: a field is pending when it has no rows, any chunk's
source_hash no longer matches the text and model, or its embedding is NULL after
fewer than MAX_ATTEMPTS failures.
"""

import hashlib
import logging

import psycopg

from matching.chunking import split_phrases
from matching.embedder import vector_literal
from matching.scoring import DEFAULT_WEIGHTS

FIELDS = tuple(DEFAULT_WEIGHTS.fields)
MAX_ATTEMPTS = 5
MAX_PHRASE_CHARS = 200

log = logging.getLogger(__name__)

# Text counts as empty when it has no non-space character, matching str.strip() for ASCII.
_HAS_TEXT_SQL = "~ '[^[:space:]]'"
_SQL_HASH = ("encode(sha256(convert_to(%s, 'UTF8') || '\\x00'::bytea || convert_to(f.body, 'UTF8')), 'hex')")


def source_hash(model_name, text):
    return hashlib.sha256(f"{model_name}\0{text}".encode("utf-8")).hexdigest()


def _field_texts(row):
    return {field: row[field] for field in FIELDS if row[field] and row[field].strip()}


def _needs_embedding(existing, digest, max_attempts):
    if existing is None or existing["source_hash"] != digest:
        return True
    return not existing["embedded"] and existing["attempts"] < max_attempts


def _phrases(text):
    # Punctuation-only text yields no phrases; embed it whole so the field is still covered.
    return split_phrases(text) or [text.strip()[:MAX_PHRASE_CHARS]]


def _store_vectors(db, student_id, model, rows):
    """rows: (field, digest, [(chunk, literal)]); replaces each field's chunks."""
    fields = [field for field, _, _ in rows]
    db.execute("DELETE FROM profile_embeddings WHERE student_id = %s AND field = ANY(%s::text[])",
               (student_id, fields))
    db.cursor().executemany("""
        INSERT INTO profile_embeddings (student_id, field, chunk, embedding, model, source_hash, attempts, last_error_at, updated_at)
        VALUES (%s, %s, %s, %s::extensions.vector, %s, %s, 0, NULL, now())
    """, [(student_id, field, chunk, literal, model, digest)
          for field, digest, chunks in rows for chunk, literal in chunks])


def _record_failure(db, student_id, model, fields, hashes):
    # A failed field is a single chunk-0 row with no embedding. attempts counts failures for the
    # current text; new text starts again from one.
    db.cursor().executemany("""
        INSERT INTO profile_embeddings (student_id, field, chunk, embedding, model, source_hash, attempts, last_error_at, updated_at)
        VALUES (%s, %s, 0, NULL, %s, %s, 1, now(), now())
        ON CONFLICT (student_id, field, chunk) DO UPDATE SET
            embedding = NULL, model = EXCLUDED.model, source_hash = EXCLUDED.source_hash,
            attempts = CASE WHEN profile_embeddings.source_hash = EXCLUDED.source_hash
                            THEN profile_embeddings.attempts + 1 ELSE 1 END,
            last_error_at = now(), updated_at = now()
    """, [(student_id, field, model, hashes[field]) for field in fields])
    db.execute("DELETE FROM profile_embeddings WHERE student_id = %s AND field = ANY(%s::text[]) AND chunk > 0",
               (student_id, fields))


def _refresh(db, embedder, student_id, max_attempts):
    row = db.execute(f"SELECT {', '.join(FIELDS)} FROM students WHERE id = %s FOR SHARE",
                     (student_id,)).fetchone()
    if row is None:
        return True
    texts = _field_texts(row)
    db.execute("SELECT 1 FROM profile_embeddings WHERE student_id = %s FOR UPDATE", (student_id,)).fetchall()
    # Chunks with differing hashes summarise to a NULL hash, i.e. stale.
    existing = {r["field"]: r for r in db.execute("""
        SELECT field,
               CASE WHEN count(DISTINCT source_hash) = 1 THEN min(source_hash) END AS source_hash,
               bool_and(embedding IS NOT NULL) AS embedded, max(attempts) AS attempts
        FROM profile_embeddings WHERE student_id = %s GROUP BY field
    """, (student_id,)).fetchall()}

    emptied = [field for field in existing if field not in texts]
    if emptied:
        db.execute("DELETE FROM profile_embeddings WHERE student_id = %s AND field = ANY(%s::text[])",
                   (student_id, emptied))

    model = embedder.model_name
    hashes = {field: source_hash(model, text) for field, text in texts.items()}
    todo = [field for field in texts if _needs_embedding(existing.get(field), hashes[field], max_attempts)]
    if not todo:
        return True
    try:
        phrases = {field: _phrases(texts[field]) for field in todo}
        flat = [phrase for field in todo for phrase in phrases[field]]
        vectors = embedder.embed_passages(flat)
        if len(vectors) != len(flat):
            raise ValueError(f"expected {len(flat)} vectors, got {len(vectors)}")
        literals = iter([vector_literal(vector) for vector in vectors])
        rows = [(field, hashes[field], [(chunk, next(literals)) for chunk in range(len(phrases[field]))])
                for field in todo]
    except Exception as error:  # any embedder failure is recorded and retried later
        log.warning("Embedding student %s fields %s failed: %s", student_id, todo, type(error).__name__)
        _record_failure(db, student_id, model, todo, hashes)
        return False
    _store_vectors(db, student_id, model, rows)
    return True


def refresh(db, embedder, student_id, max_attempts=MAX_ATTEMPTS):
    """Embed the student's changed fields and drop emptied ones; True when all are current.

    Runs in a savepoint, so neither embedder nor database failures abort the
    caller's transaction; a failure is recorded (or left pending) for the sweeper.
    """
    try:
        with db.transaction():
            return _refresh(db, embedder, student_id, max_attempts)
    except psycopg.Error as error:
        log.warning("Storing embeddings for student %s failed: %s", student_id, type(error).__name__)
        return False


def pending_student_ids(db, model_name, limit=100, max_attempts=MAX_ATTEMPTS):
    """Students with a field whose embedding is missing, stale, retryable, or no longer needed."""
    values = ", ".join(f"('{field}', s.{field})" for field in FIELDS)
    rows = db.execute(f"""
        SELECT s.id
        FROM students s
        CROSS JOIN LATERAL (VALUES {values}) AS f(field, body)
        LEFT JOIN profile_embeddings pe ON pe.student_id = s.id AND pe.field = f.field
        WHERE CASE WHEN COALESCE(f.body {_HAS_TEXT_SQL}, false) THEN
                  pe.student_id IS NULL
                  OR pe.source_hash <> {_SQL_HASH}
                  OR (pe.embedding IS NULL AND pe.attempts < %s)
              ELSE pe.student_id IS NOT NULL END
        GROUP BY s.id
        ORDER BY s.id
        LIMIT %s
    """, (model_name, max_attempts, limit)).fetchall()
    return [row["id"] for row in rows]


def sweep(db_factory, embedder, limit=100, max_attempts=MAX_ATTEMPTS):
    """Refresh up to `limit` pending students, one transaction each; returns (done, failed)."""
    with db_factory() as db:
        student_ids = pending_student_ids(db, embedder.model_name, limit, max_attempts)
    done = failed = 0
    for student_id in student_ids:
        with db_factory() as db:
            if refresh(db, embedder, student_id, max_attempts):
                done += 1
            else:
                failed += 1
    return done, failed
