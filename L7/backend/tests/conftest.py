# fixture comuni: database PostgreSQL di prova (TEST_DATABASE_URL), tabelle ricreate per ogni test
import os

import pytest
from sqlalchemy.engine import make_url

from app.db import Base, crea_motore, fabbrica_sessioni

MOTIVO_SALTO = "avvia il container l6-postgres e imposta TEST_DATABASE_URL"


# motore unico per tutta la sessione di test; senza TEST_DATABASE_URL i test del database saltano
@pytest.fixture(scope="session")
def motore():
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip(MOTIVO_SALTO)
    # protezione dei dati veri: i test cancellano tutte le tabelle
    if not (make_url(url).database or "").endswith("_test"):
        pytest.exit("TEST_DATABASE_URL deve indicare un database il cui nome finisce con _test")
    m = crea_motore(url)
    yield m
    m.dispose()


# fabbrica di sessioni su tabelle vuote: drop_all + create_all prima di ogni test
@pytest.fixture
def fabbrica(motore):
    Base.metadata.drop_all(motore)
    Base.metadata.create_all(motore)
    return fabbrica_sessioni(motore)
