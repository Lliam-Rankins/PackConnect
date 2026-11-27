"""Optional scheduled maintenance: python backend/embed_profiles.py."""

from app import app, get_db
from matching import profile_vectors

if __name__ == "__main__":
    done, failed = profile_vectors.sweep(get_db, app.config["EMBEDDER"])
    print(f"Embedded {done} profiles; {failed} failed and will be retried.")
