"""Raster image evidence pipeline (Phase B, P3). Bounded decode, crops, OCR,
deterministic spatial extraction — image evidence is never canonical identity.
"""

from umd.raster.bounds import (
    CropOutOfBoundsError,
    RasterDecodeError,
    RasterError,
    RasterImage,
    RasterLimits,
    RasterLimitsExceeded,
    decode_bounded,
)
from umd.raster.crops import CropRecord, retrieve_crop, store_crop
from umd.raster.ocr import (
    PROVIDERS,
    OcrConfig,
    OcrError,
    OcrProvider,
    OcrProviderUnavailable,
    OcrRegion,
    OcrResult,
    PaddleOcrProvider,
    ReferenceOcrProvider,
    TesseractOcrProvider,
    run_ocr,
)
from umd.raster.pipeline import (
    RASTER_PIPELINE_VERSION,
    RasterPipelineConfig,
    RasterProcessResult,
    process_raster,
)
from umd.raster.regions import Box, Region, detect_panels, find_ink_regions
from umd.raster.spatial import (
    CandidateObservation,
    ReferenceSpatialProvider,
    SpatialObservation,
    SpatialProvider,
    SpatialResult,
    run_spatial,
)

__all__ = [
    "Box",
    "CandidateObservation",
    "CropOutOfBoundsError",
    "CropRecord",
    "OcrConfig",
    "OcrError",
    "OcrProvider",
    "OcrProviderUnavailable",
    "OcrRegion",
    "OcrResult",
    "PROVIDERS",
    "PaddleOcrProvider",
    "RASTER_PIPELINE_VERSION",
    "RasterDecodeError",
    "RasterError",
    "RasterImage",
    "RasterLimits",
    "RasterLimitsExceeded",
    "RasterPipelineConfig",
    "RasterProcessResult",
    "ReferenceOcrProvider",
    "ReferenceSpatialProvider",
    "Region",
    "SpatialObservation",
    "SpatialProvider",
    "SpatialResult",
    "TesseractOcrProvider",
    "decode_bounded",
    "detect_panels",
    "find_ink_regions",
    "process_raster",
    "retrieve_crop",
    "run_ocr",
    "run_spatial",
    "store_crop",
]
