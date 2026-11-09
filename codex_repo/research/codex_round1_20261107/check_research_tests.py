"""Run historical tests in scratch space without rewriting archived result JSONs."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    package=Path(__file__).resolve().parent
    repository=package.parents[1]
    original=package/'outputs/qminers-algo-arena'
    scratch=(repository/'logs/codex_archive_checks').resolve()
    scratch.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tests-',dir=scratch) as directory:
        project=Path(directory).resolve()
        assert project.is_relative_to(scratch)
        shutil.copytree(original/'strategies',project/'strategies')
        research=project/'research'
        (research/'results').mkdir(parents=True)
        for source in (original/'research').glob('*.py'):
            shutil.copyfile(source,research/source.name)
        environment=dict(os.environ,PYTHONPATH=str(repository))
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(research),'-p','test_*.py'],
            cwd=repository,env=environment,check=False)
        return result.returncode


if __name__=='__main__':
    raise SystemExit(main())
