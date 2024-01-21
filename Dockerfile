FROM nvidia/cuda:12.1.0-devel-ubuntu22.04

RUN apt-get update
RUN apt-get install --no-install-recommends -y bash git vim nano mc build-essential python3-dev python3-venv python3-pip

WORKDIR /install
COPY ./requirements.txt /install
COPY ./requirements-all.txt /install

RUN pip install --use-deprecated=legacy-resolver -r requirements-all.txt
RUN pip uninstall -y torch torchvision torchaudio torchtext
RUN pip install --pre torch --index-url https://download.pytorch.org/whl/nightly/cu121
RUN pip install -U datasets

WORKDIR /repo

ENTRYPOINT ["tail", "-f", "/dev/null"]
