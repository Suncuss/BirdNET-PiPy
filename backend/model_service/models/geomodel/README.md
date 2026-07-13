# BirdNET+ Geomodel assets

These files are unmodified release artifacts from BirdNET+ Geomodel v3.0.3,
renamed to stable application paths so existing BirdNET-PiPy installations can
upgrade without configuration changes.

- Project: https://github.com/birdnet-team/geomodel
- Release: https://github.com/birdnet-team/geomodel/releases/tag/v3.0.3
- Model: FP16 ONNX weights with FP32 input and output tensors
- Input: `[latitude, longitude, week]`
- Output: 12,314 independent sigmoid occurrence probabilities in label-file order

The exact upstream filenames, sizes, checksums, tensor contract, and source
commit are recorded in `manifest.json`. Image builds and runtime startup verify
the model, labels, and license against that manifest before enabling location
filtering.

The model weights are distributed under the terms in `MODEL_LICENSE.txt`.
