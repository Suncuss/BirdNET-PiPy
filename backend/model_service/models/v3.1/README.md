# BirdNET V3.1 acoustic model bundle

BirdNET-PiPy calls this bundled acoustic release **BirdNET V3.1**. Upstream
publishes the same release as **BirdNET+ V3.0 Developer Preview 3.1**.

- Source: https://github.com/birdnet-team/birdnet-V3.0-dev
- Release: https://zenodo.org/records/20703646
- DOI: 10.5281/zenodo.20703646

The model, labels, and terms are unmodified upstream release artifacts. Their
exact sizes, SHA-256 digests, and tensor contract are recorded in
`manifest.json`. BirdNET-PiPy also removes the obsolete V3.0 model path and any
partial-download residue after an updated model service starts successfully.

The model weights are licensed under CC BY-SA 4.0 and remain subject to the
bundled `TERMS_OF_USE.txt`. Image builds and runtime startup validate the
inference artifacts before the model is used.
