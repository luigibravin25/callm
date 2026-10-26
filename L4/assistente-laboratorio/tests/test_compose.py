import shutil
import subprocess
from pathlib import Path

import pytest

PROGETTO = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("docker") is None,
                    reason="eseguibile 'docker' non trovato nel PATH")
def test_compose_valido():
    # solo validazione della configurazione: niente LM Studio, niente container
    r = subprocess.run(["docker", "compose", "config"], cwd=PROGETTO,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "host.docker.internal" in r.stdout
    assert "app:" in r.stdout
