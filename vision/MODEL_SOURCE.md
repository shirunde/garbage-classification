# Vision model provenance

The initial board-side detector uses `blocks4_yolov8n.om` from the public release `assets-v4` of [anweat/vision-robot-arm-sorting](https://github.com/anweat/vision-robot-arm-sorting/releases/tag/assets-v4).

The release targets Atlas 200I DK A2 / Ascend310B1 and contains matching ONNX and PyTorch weights. Its model contract is 640×640 RGB input, float values divided by 255, and output shaped `[1, 8, 8400]`. The exported class-ID order is `recyclable`, `kitchen`, `hazardous`, `other`; map IDs by these names because this project's shared schema orders `hazardous` and `kitchen` differently.

Upstream reports training on 136 real images plus 800 synthetic images and reports mAP@0.5 of 0.952. These are upstream figures, not measurements on this board. The release does not disclose per-class sample counts or provide the dataset, so it does not satisfy this course's data-proportion reporting requirement by itself. Collect and label at least 200 images per class from the actual work area for the final evaluation, and record the source and class counts before making a final acceptance claim.

The upstream README identifies the weights as Ultralytics YOLOv8n under AGPL-3.0 and says the assets are intended for the course project. Keep the release provenance with any redistribution.
